from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from loom.graph.db import DB
from loom.graph.db_pool import DBPool
from loom.graph.projects import ProjectRegistry
from loom.server.tools import search as search_tool


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


def _seed(db: DB, fn_name: str) -> None:
    """Insert one node so search can return something."""
    conn = db.connect()
    now = int(time.time())
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, start_line, end_line, "
        "language, content_hash, summary, summary_hash, token_count, metadata, "
        "updated_at, deleted_at) "
        "VALUES (?, 'function', 'code', ?, ?, 1, 2, 'python', 'h', NULL, NULL, 10, '{}', ?, NULL)",
        (f"function:src/{fn_name}.py:{fn_name}:1", fn_name, f"src/{fn_name}.py", now),
    )
    conn.commit()


@pytest.fixture()
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DBPool:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    for proj, sym in (("alpha", "alpha_only_fn"), ("beta", "beta_only_fn")):
        db = DB(path=pdir / f"{proj}.db")
        _seed(db, sym)
        db.close()
    monkeypatch.chdir(tmp_path)
    # Also create a "current" project DB so default resolution works.
    cur = DB(path=pdir / f"{tmp_path.name}.db")
    _seed(cur, "cwd_only_fn")
    cur.close()
    return DBPool(ProjectRegistry(projects_dir=pdir))


@pytest.mark.asyncio
async def test_project_arg_routes_to_correct_db(pool: DBPool) -> None:
    mcp = FakeMCP()
    search_tool.register(mcp, pool, {}, None)
    res = await mcp.tools["search_code"](query="alpha_only_fn", project="alpha")
    assert res["ok"] is True
    names = [r["name"] for r in res["data"]]
    assert "alpha_only_fn" in names

    res2 = await mcp.tools["search_code"](query="beta_only_fn", project="beta")
    assert res2["ok"] is True
    names2 = [r["name"] for r in res2["data"]]
    assert "beta_only_fn" in names2


@pytest.mark.asyncio
async def test_unknown_project_returns_validation_error(pool: DBPool) -> None:
    mcp = FakeMCP()
    search_tool.register(mcp, pool, {}, None)
    res = await mcp.tools["search_code"](query="x", project="missing")
    # err() returns {"ok": False, "error_code": ..., "message": ...} (flat shape)
    assert res["ok"] is False
    assert "missing" in res["message"]


@pytest.mark.asyncio
async def test_project_none_uses_current(pool: DBPool) -> None:
    mcp = FakeMCP()
    search_tool.register(mcp, pool, {}, None)
    res = await mcp.tools["search_code"](query="cwd_only_fn")
    assert res["ok"] is True
    names = [r["name"] for r in res["data"]]
    assert "cwd_only_fn" in names
