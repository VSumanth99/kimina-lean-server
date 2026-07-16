"""Tests for REPL header preparation."""

import asyncio
from typing import Any

import pytest
from kimina_client import ReplResponse

from server.manager import Manager
from server.repl import Repl


@pytest.mark.asyncio
async def test_prep_uses_server_header_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = Manager(
        max_repls=2,
        max_repl_uses=1,
        max_repl_mem=8192,
        header_timeout=300.0,
        init_repls={},
    )
    repl = await Repl.create("import Mathlib", 1, 8192)
    seen_timeout: float | None = None

    async def fake_start() -> None:
        return None

    async def fake_prep_header(
        _repl: Repl, _snippet_id: str, timeout: float, _debug: bool
    ) -> ReplResponse:
        nonlocal seen_timeout
        seen_timeout = timeout
        return ReplResponse(id="header", response={"env": 0})

    monkeypatch.setattr(repl, "start", fake_start)
    monkeypatch.setattr(manager, "_prep_header", fake_prep_header)

    await manager.prep(repl, "test", timeout=30.0, debug=False)

    assert seen_timeout == 300.0


@pytest.mark.asyncio
async def test_prep_does_not_serialize_identical_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = Manager(
        max_repls=2,
        max_repl_uses=1,
        max_repl_mem=8192,
        header_timeout=300.0,
        init_repls={},
    )
    repls = [
        await Repl.create("import Mathlib", 1, 8192),
        await Repl.create("import Mathlib", 1, 8192),
    ]
    both_started = asyncio.Event()
    started = 0

    async def fake_start() -> None:
        return None

    async def fake_prep_header(*_args: Any, **_kwargs: Any) -> ReplResponse:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await both_started.wait()
        return ReplResponse(id="header", response={"env": 0})

    for repl in repls:
        monkeypatch.setattr(repl, "start", fake_start)
    monkeypatch.setattr(manager, "_prep_header", fake_prep_header)

    await asyncio.wait_for(
        asyncio.gather(
            manager.prep(repls[0], "first", timeout=30.0, debug=False),
            manager.prep(repls[1], "second", timeout=30.0, debug=False),
        ),
        timeout=1.0,
    )

    assert started == 2
