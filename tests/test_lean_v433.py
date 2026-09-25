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
        assert rule["goalsBefore"] != rule["goalsAfter"]
        if i:
            assert rules[i - 1]["goalsAfter"] == rule["goalsBefore"]
    if at_hypothesis:
        assert "h : d + 1 = 10" in rules[-1]["goalsAfter"][0]
    elif tactic == "simp_rw":
        assert rules[-1]["goalsAfter"] == []
    else:
        assert rules[-1]["goalsAfter"][0].endswith("⊢ d + 1 = d + 1")


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


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_ast_preserves_unicode_spans_and_local_notation(client: TestClient) -> None:
    """Statement extraction needs original byte offsets and local syntax."""
    code = (
        "import Mathlib\n"
        "namespace AstCompatibility\n"
        'notation "ℙ" => Prop\n'
        "theorem α (P : ℙ) (h : P) : P := by exact h\n"
        "theorem β (P : ℙ) (h : P) : P := α P h\n"
        "end AstCompatibility\n"
    )
    response = client.post("ast_code", json={"code": code, "timeout": 60})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert not result.get("error"), result
    ast = result["ast"]
    assert ast["header"] and len(ast["commands"]) == 5

    # Inspect every source token, including those following multibyte characters.
    pending = list(ast["commands"])
    tokens = []
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            pending.extend(node.get("args", []))
            info = node.get("info") or {}
            if "val" in node and "pos" in info and not info.get("synthetic"):
                start, end = info["pos"]
                token = code.encode("utf-8")[start:end].decode("utf-8")
                assert token == node.get("rawVal", node["val"])
                tokens.append(token)
    assert "α" in tokens and "β" in tokens and "ℙ" in tokens


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
def test_module_header_and_tactic_sequences(client: TestClient) -> None:
    """New module headers must work with the server's reusable environments."""
    code = (
        "module\n"
        "public import Mathlib\n\n"
        "public theorem module_demo (n : Nat) : n + 0 = n := by\n"
        "  simp\n"
    )
    response = client.post(
        "check",
        json={
            "snippets": [{"id": "module-header", "code": code}],
            "tactic_sequences": True,
            "timeout": 60,
        },
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert not [m for m in output.get("messages", []) if m["severity"] == "error"]
    assert not output.get("sorries")
    assert any(
        tactic["tactic"] == "simp" and tactic["goalsAfter"] == []
        for sequence in output["tacticSequences"]
        for tactic in sequence["tactics"]
    )

    # The same source must also succeed after its worker has been reused.
    response = client.post(
        "check",
        json={"snippets": [{"id": "module-again", "code": code}], "timeout": 60},
    )
    result = response.json()["results"][0]
    assert not result.get("error"), result
    assert not [
        m for m in result["response"].get("messages", []) if m["severity"] == "error"
    ], result

    response = client.post("ast_code", json={"code": code, "timeout": 60})
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert not result.get("error"), result
    assert len(result["ast"]["commands"]) == 1


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
@pytest.mark.parametrize("proof", ["sorry", "by sorry", "by admit"])
def test_sorry_remains_visible_to_existing_clients(client: TestClient, proof: str) -> None:
    """Both structured and legacy message-based clients must reject placeholders."""
    response = client.post(
        "check",
        json={"snippets": [{"id": "sorry", "code": f"example : False := {proof}"}]},
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert not result.get("error"), result
    output = result["response"]
    assert output.get("sorries"), output
    assert any(
        m["severity"] == "warning" and m["data"] == "declaration uses 'sorry'"
        for m in output["messages"]
    )
