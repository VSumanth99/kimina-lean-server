"""Structured proof states must preserve information lost by goal-text parsing."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_structured_goals_preserve_locals_and_saved_states(client: TestClient) -> None:
    code = """set_option pp.showLetValues false
set_option pp.showLetValues.tactic.threshold 0
example (P : Prop) (hp : P) : P := by
  have «two words» : P := hp
  have «h:colon» : P := hp
  let n : Nat := 37 + 1
  skip
  exact «two words»
"""
    result = client.post("check", json={
        "snippets": [{"id": "locals", "code": code}], "tactic_sequences": True,
    }).json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    assert not output.get("infotree")
    entries = [entry for seq in output["tacticSequences"] for entry in seq["tactics"]]
    skip = next(entry for entry in entries if entry["tactic"] == "skip")
    assert skip["goalStatesBefore"] == skip["goalStatesAfter"]
    goal = skip["goalStatesBefore"][0]
    assert goal["id"] and goal["target"] == "P"
    locals_by_name = {local["name"]: local for local in goal["locals"]}
    assert len({local["id"] for local in goal["locals"]}) == len(goal["locals"])
    assert locals_by_name["«two words»"]["type"] == "P"
    assert locals_by_name["«h:colon»"]["type"] == "P"
    assert locals_by_name["hp"].get("value") is None
    assert locals_by_name["n"]["value"] == "37 + 1"
    assert "goalsBefore" not in skip and "goalsAfter" not in skip
    # The final context must not leak backwards into earlier saved states.
    first = next(entry for entry in entries if entry["tactic"].startswith("have «two words»"))
    before = first["goalStatesBefore"][0]["locals"]
    assert [local["name"] for local in before] == ["P", "hp"]
    assert before[1]["id"] == locals_by_name["hp"]["id"]
    final = next(entry for entry in entries if entry["tactic"] == "exact «two words»")
    assert final["goalStatesAfter"] == []


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_structured_goal_ids_follow_goals_through_reordering(client: TestClient) -> None:
    code = """import Mathlib
example (P Q : Prop) (hp : P) (hq : Q) : P ∧ Q := by
  constructor
  swap
  exact hq
  exact hp
"""
    result = client.post("check", json={
        "snippets": [{"id": "reorder", "code": code}], "tactic_sequences": True,
    }).json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    swap = next(entry for seq in output["tacticSequences"] for entry in seq["tactics"]
                if entry["tactic"] == "swap")
    before, after = swap["goalStatesBefore"], swap["goalStatesAfter"]
    assert len(before) == len(after) == 2
    assert before[0]["id"] != before[1]["id"]
    assert before == list(reversed(after))


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_structured_targets_preserve_spaces_inside_literals(client: TestClient) -> None:
    code = '''import Mathlib
example (h : "a b" = "a  b") : "a b" = "a  b" := by
  conv_lhs => rw [h]
'''
    result = client.post("check", json={
        "snippets": [{"id": "strings", "code": code}], "tactic_sequences": True,
    }).json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    entry = next(entry for seq in output["tacticSequences"] for entry in seq["tactics"]
                 if entry["tactic"].startswith("conv_lhs"))
    assert entry["goalStatesBefore"][0]["target"] == '"a b" = "a  b"'
    # The conversion tactic may close the reflexive equality itself.
    targets = [goal["target"] for seq in output["tacticSequences"] for tactic in seq["tactics"]
               for goal in tactic["goalStatesBefore"] + tactic["goalStatesAfter"]]
    assert any('"a  b"' in target for target in targets)
