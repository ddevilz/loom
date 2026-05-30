from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loom.graph.db import DB
from loom.graph.db_pool import DBPool
from loom.graph.projects import ProjectRegistry
from loom.server.tools import projects as projects_tool


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture()
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DBPool:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    for name in ("alpha", "beta"):
        db = DB(path=pdir / f"{name}.db")
        db.connect()
        db.close()
    monkeypatch.chdir(tmp_path)
    return DBPool(ProjectRegistry(projects_dir=pdir))


@pytest.mark.asyncio
async def test_list_projects_returns_all(pool: DBPool) -> None:
    mcp = FakeMCP()
    projects_tool.register(mcp, pool, {}, None)
    result = await mcp.tools["list_projects"]()
    assert result["ok"] is True
    names = sorted(p["name"] for p in result["data"]["projects"])
    assert names == ["alpha", "beta"]
    assert "current" in result["data"]


@pytest.mark.asyncio
async def test_list_projects_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    monkeypatch.chdir(tmp_path)
    pool = DBPool(ProjectRegistry(projects_dir=pdir))
    mcp = FakeMCP()
    projects_tool.register(mcp, pool, {}, None)
    result = await mcp.tools["list_projects"]()
    assert result["ok"] is True
    assert result["data"]["projects"] == []
