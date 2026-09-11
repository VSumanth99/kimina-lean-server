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
@pytest.mark.parametrize("module", ["Mathlib", "Mathlib.Data.Nat.Basic"])
async def test_ast_module_mathlib(client: TestClient, module: str) -> None:
    resp = client.post(
        "ast",
        json={
            "modules": [module],
            "one": True,
            "timeout": 60,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data and len(data["results"]) == 1
    assert data["results"][0]["module"] == module
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
    assert data["results"][0]["module"].startswith("User.Code_")
    assert data["results"][0].get("error") is None
    assert isinstance(data["results"][0]["ast"], dict)
