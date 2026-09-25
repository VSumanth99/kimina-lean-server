"""Integration checks for the Lean 4.33 features consumed by informalization."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
@pytest.mark.parametrize("tactic", ["rw", "erw", "rewrite", "simp_rw", "nth_rw 1", "rw_at"])
def test_rewrite_rules_export_checked_intermediate_states(client: TestClient, tactic: str) -> None:
    """Rule states use source spans and need no original-infotree response."""
    at_hypothesis = tactic == "rw_at"
    source = (
        "import Mathlib\n"
        "example (a b c d : ℕ) (h₁ : a = b) (h₂ : b = c) (h₃ : c = d) "
        + ("(h : a + 1 = 10) : d + 1 = 10 := by\n" if at_hypothesis
           else ": a + 1 = d + 1 := by\n")
        + f"  {'rw' if at_hypothesis else tactic} [h₁, h₂, h₃]"
        + (" at h\n  exact h\n" if at_hypothesis else "\n")
        + ("  rfl\n" if tactic == "rewrite" else "")
    )
    response = client.post("check", json={
        "snippets": [{"id": tactic, "code": source}],
        "tactic_sequences": True, "timeout": 60,
    })
    result = response.json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not output.get("infotree")
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    rules = [entry for seq in output["tacticSequences"] for entry in seq["tactics"]
             if entry["name"] == "Lean.Parser.Tactic.rwRule"]
    assert [rule["tactic"] for rule in rules] == ["h₁", "h₂", "h₃"]
    for i, rule in enumerate(rules):
        line = source.splitlines()[rule["pos"]["line"]]  # one import line is removed
        assert line[rule["pos"]["column"]:rule["endPos"]["column"]] == rule["tactic"]
        assert rule["goalStatesBefore"] != rule["goalStatesAfter"]
        if i:
            assert rules[i - 1]["goalStatesAfter"] == rule["goalStatesBefore"]
    if at_hypothesis:
        assert any(local["name"] == "h" and local["type"] == "d + 1 = 10"
                   for local in rules[-1]["goalStatesAfter"][0]["locals"])
    elif tactic == "simp_rw":
        assert rules[-1]["goalStatesAfter"] == []
    else:
        assert rules[-1]["goalStatesAfter"][0]["target"] == "d + 1 = d + 1"


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_single_rewrite_does_not_add_rule_detail(client: TestClient) -> None:
    response = client.post("check", json={
        "snippets": [{"id": "single", "code": "example (a b : Nat) (h : a = b) : a = b := by rw [h]"}],
        "tactic_sequences": True,
    })
    result = response.json()["results"][0]
    assert not result.get("error"), result
    assert not [m for m in result["response"].get("messages", []) if m["severity"] == "error"]
    assert all(entry["name"] != "Lean.Parser.Tactic.rwRule"
               for seq in result["response"]["tacticSequences"] for entry in seq["tactics"])


