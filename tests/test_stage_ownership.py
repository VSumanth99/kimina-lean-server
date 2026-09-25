"""Checked rewrite stages retain their actual execution owner and order."""

from collections import defaultdict

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
@pytest.mark.parametrize("body,target,counts", [
    ("rw [h₁, h₂]", "a + 1 = c + 1", [2]),
    ("constructor <;> rw [h₁, h₂]", "a = c ∧ a = c", [2, 2]),
    ("rw [show a = c by rw [h₁, h₂], h₃]", "a = d", [2, 2]),
    ("rw [h₁, h₂] at ha ⊢\n  exact ha", "a = 0", [2]),
])
def test_stages_identify_their_own_execution(client: TestClient, body: str, target: str, counts: list[int]) -> None:
    code = (
        "import Mathlib\n"
        "example (a b c d : Nat) (h₁ : a = b) (h₂ : b = c) (h₃ : c = d) "
        f"(ha : a = 0) : {target} := by\n  {body}\n"
        "example : True := by trivial\n"
    )
    result = client.post("check", json={
        "snippets": [{"id": "owners", "code": code}], "tactic_sequences": True,
    }).json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    entries = [entry for seq in output["tacticSequences"] for entry in seq["tactics"]]
    by_id = {entry["executionId"]: entry for entry in entries}
    assert len(by_id) == len(entries)
    stages = defaultdict(list)
    for entry in entries:
        assert "goalsBefore" not in entry and "goalsAfter" not in entry
        if "ownerId" in entry:
            assert entry["ownerId"] in by_id
            owner = by_id[entry["ownerId"]]
            assert "ownerId" not in owner
            assert owner["pos"]["line"] <= entry["pos"]["line"] <= owner["endPos"]["line"]
            stages[entry["ownerId"]].append(entry)
        else:
            assert "stageIndex" not in entry
    assert sorted(len(group) for group in stages.values()) == counts
    for group in stages.values():
        assert [entry["stageIndex"] for entry in group] == list(range(1, len(group) + 1))
