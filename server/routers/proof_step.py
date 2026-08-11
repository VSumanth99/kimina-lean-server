import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends
from kimina_client import (
    Error,
    ProofStep,
    ProofStepCheckRequest,
    ProofStepCheckResponse,
    ProofStepResponse,
    Snippet,
)

from ..auth import require_key
from ..manager import Manager
from ..repl import Repl
from ..split import split_snippet
from .check import get_manager

router = APIRouter()


def _normalize_goal(goal: str) -> str:
    """Normalize rendered goal whitespace for replay-state matching."""

    return re.sub(r"\s+", " ", goal).strip()


def _position_in_tactic(tactic: dict[str, Any], line: int, column: int) -> bool:
    """Return whether a Lean source position lies in a tactic span."""

    start = tactic.get("pos")
    end = tactic.get("endPos")
    if not isinstance(start, dict) or not isinstance(end, dict):
        return False
    position = (line, column)
    return (
        (int(start["line"]), int(start["column"]))
        <= position
        <= (int(end["line"]), int(end["column"]))
    )


def _select_tactic(
    tactics: list[dict[str, Any]],
    *,
    line: int,
    column: int,
    before_goal: str,
) -> dict[str, Any] | None:
    """Select the narrowest tactic snapshot at the requested pre-state."""

    normalized_before = _normalize_goal(before_goal)
    candidates = [
        tactic
        for tactic in tactics
        if isinstance(tactic.get("proofState"), int)
        and _position_in_tactic(tactic, line, column)
        and normalized_before in _normalize_goal(str(tactic.get("goals", "")))
    ]
    if not candidates:
        return None

    def span_size(tactic: dict[str, Any]) -> tuple[int, int]:
        start = tactic["pos"]
        end = tactic["endPos"]
        return (
            int(end["line"]) - int(start["line"]),
            int(end["column"]) - int(start["column"]),
        )

    return min(candidates, key=span_size)


def _failure(
    request: ProofStepCheckRequest,
    status: str,
    error: str,
    *,
    elapsed: float = 0.0,
) -> ProofStepCheckResponse:
    """Build one rejected proof-step response."""

    return ProofStepCheckResponse(
        id=request.snippet.id,
        accepted=False,
        status=status,
        error=error,
        time=elapsed,
    )


def _proof_step_error(response: ProofStepResponse | Error) -> str | None:
    """Return a Lean error or forbidden sorry reported by a proof step."""

    if "message" in response:
        error = response
        return str(error["message"])
    messages = response.get("messages") or []
    error_messages = [
        str(message.get("data", "Lean proof-step error"))
        for message in messages
        if message.get("severity") == "error"
    ]
    if error_messages:
        return "\n".join(error_messages)
    if response.get("sorries"):
        return "proof-step certificate cannot contain sorry"
    return None


@router.post(
    "/proof-step/check",
    response_model=ProofStepCheckResponse,
    response_model_exclude_none=True,
)
async def check_proof_step(
    request: ProofStepCheckRequest,
    manager: Manager = Depends(get_manager),
    _: str = Depends(require_key),
) -> ProofStepCheckResponse:
    """Replay one tactic and check a declaration in its exact post-state."""

    repl: Repl | None = None
    elapsed = 0.0
    try:
        header, body = split_snippet(request.snippet.code)
        repl = await manager.get_repl(
            header,
            request.snippet.id,
            timeout=float(request.timeout),
            reuse=request.reuse,
        )
        prep = await manager.prep(
            repl,
            request.snippet.id,
            float(request.timeout),
            request.debug,
        )
        if prep is not None and prep.error:
            return _failure(request, "source_error", prep.error)

        source_result = await repl.send_timeout(
            Snippet(id=request.snippet.id, code=body),
            timeout=float(request.timeout),
            all_tactics=True,
        )
        elapsed += source_result.time
        source_response = source_result.response
        if not isinstance(source_response, dict) or "message" in source_response:
            return _failure(
                request,
                "source_error",
                str(source_response or "Kimina returned no source response"),
                elapsed=elapsed,
            )

        selected = _select_tactic(
            list(source_response.get("tactics") or []),
            line=request.line,
            column=request.column,
            before_goal=request.before_goal,
        )
        if selected is None:
            return _failure(
                request,
                "state_not_found",
                "No tactic proof state matched the requested position and pre-goal",
                elapsed=elapsed,
            )

        mutation_response, mutation_time, _ = await asyncio.wait_for(
            repl.run_proof_step(
                ProofStep(
                    proofState=int(selected["proofState"]),
                    tactic=str(selected["tactic"]),
                )
            ),
            timeout=float(request.timeout),
        )
        elapsed += mutation_time
        mutation_error = _proof_step_error(mutation_response)
        if mutation_error is not None:
            return _failure(
                request,
                "mutation_replay_error",
                mutation_error,
                elapsed=elapsed,
            )

        expected_after = _normalize_goal(request.after_goal)
        if not any(
            _normalize_goal(goal) == expected_after
            for goal in mutation_response.get("goals", [])
        ):
            return _failure(
                request,
                "residual_goal_mismatch",
                "Replayed tactic did not produce the requested residual goal",
                elapsed=elapsed,
            )

        certificate_response, certificate_time, _ = await asyncio.wait_for(
            repl.run_proof_step(
                ProofStep(
                    proofState=int(mutation_response["proofState"]),
                    tactic=request.certificate_tactic,
                )
            ),
            timeout=float(request.timeout),
        )
        elapsed += certificate_time
        certificate_error = _proof_step_error(certificate_response)
        if certificate_error is not None:
            return _failure(
                request,
                "certificate_rejected",
                certificate_error,
                elapsed=elapsed,
            )

        response: ProofStepResponse = certificate_response
        return ProofStepCheckResponse(
            id=request.snippet.id,
            accepted=True,
            status="accepted",
            response=response,
            time=elapsed,
        )
    except (asyncio.TimeoutError, TimeoutError):
        if repl is not None:
            await repl.kill_immediately()
        return _failure(
            request,
            "timeout",
            f"Proof-step check timed out after {request.timeout}s",
            elapsed=elapsed,
        )
    except Exception as error:
        return _failure(
            request,
            "server_error",
            str(error),
            elapsed=elapsed,
        )
    finally:
        if repl is not None:
            await manager.release_repl(repl)
