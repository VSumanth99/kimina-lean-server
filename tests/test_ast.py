import pytest
from fastapi.testclient import TestClient

from server.settings import settings


def _ast_tools_available() -> bool:
    """Return True if ast_export tooling is available in the workspace."""
    return (
        settings.ast_export_project_dir is not None
        and settings.ast_export_project_dir.exists()
        and settings.ast_export_bin is not None
        and settings.ast_export_bin.exists()
        and settings.project_dir is not None
        and settings.project_dir.exists()
    )


pytestmark = pytest.mark.skipif(
    not _ast_tools_available(),
    reason="AST export tooling not available (run `kimina-ast-server setup`)",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [
        {"database_url": None},
    ],
    indirect=True,
)
async def test_ast_module_mathlib(client: TestClient) -> None:
    resp = client.post(
        "ast",
        json={
            "modules": ["Mathlib"],
            "one": True,
            "timeout": 60,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data and len(data["results"]) == 1
    assert data["results"][0]["module"] == "Mathlib"
    assert data["results"][0].get("error") is None
    assert isinstance(data["results"][0]["ast"], dict)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [
        {"database_url": None},
    ],
    indirect=True,
)
async def test_ast_code_simple(client: TestClient) -> None:
    resp = client.post(
        "ast_code",
        json={
            "code": "import Mathlib\n#check Nat",
            "module": "User.Code",
            "timeout": 60,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data and len(data["results"]) == 1
    assert data["results"][0].get("error") is None
    assert isinstance(data["results"][0]["ast"], dict)


@pytest.mark.parametrize("client", [{"database_url": None}], indirect=True)
@pytest.mark.parametrize(
    "leading, body",
    [
        ("", "example : True := by trivial\n"),
        ("-- File comment αβ\n", "example : True := by trivial\n"),
        ("/- Outer /- nested -/ αβ -/\n", "example : True := by trivial\n"),
        ("-- Only a comment αβ\n", ""),
        ("/- Only a /- nested -/ comment -/", ""),
        ("-- Before imports\n", "import Mathlib\n#check Nat\n"),
        ("-- Before invalid code\n", "not_a_command\nexample : True := by trivial\n"),
        ("-- Before documentation\n", "/-- Declaration docs -/\ndef text := \"-- string -/\"\n"),
    ],
)
def test_ast_header_keeps_leading_comments(
    client: TestClient, leading: str, body: str
) -> None:
    """Expose initial comment bytes without consuming code or documentation."""
    response = client.post(
        "ast_code", json={"code": leading + body, "timeout": 60}
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert not result.get("error"), result
    info = result["ast"]["header"]["info"]
    assert info["leading"] == leading
    assert info["pos"][0] == len(leading.encode("utf-8"))
