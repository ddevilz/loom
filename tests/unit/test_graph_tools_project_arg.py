from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from loom.graph.db import DB
from loom.graph.db_pool import DBPool
from loom.graph.projects import ProjectRegistry
from loom.server.tools import graph as graph_tool


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeCache:
    def make_key(self, *args, **kwargs):
        return None

    def get(self, key):
        return None

    def set(self, key, value):
        pass

    def invalidate(self, key):
        pass


def _seed_node(db: DB, node_id: str, name: str) -> None:
    conn = db.connect()
    now = int(time.time())
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, start_line, end_line, "
        "language, content_hash, summary, summary_hash, token_count, metadata, "
        "updated_at, deleted_at) "
        "VALUES (?, 'function', 'code', ?, ?, 1, 2, 'python', 'h', NULL, NULL, 10, '{}', ?, NULL)",
        (node_id, name, f"src/{name}.py", now),
    )
    conn.commit()


@pytest.fixture()
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DBPool:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    for proj, sym in (("alpha", "alpha_fn"), ("beta", "beta_fn")):
        db = DB(path=pdir / f"{proj}.db")
        _seed_node(db, f"function:src/{sym}.py:{sym}:1", sym)
        db.close()
    monkeypatch.chdir(tmp_path)
    return DBPool(ProjectRegistry(projects_dir=pdir))


@pytest.mark.asyncio
async def test_get_neighbors_unknown_project_returns_error(pool: DBPool) -> None:
    mcp = FakeMCP()
    graph_tool.register(mcp, pool, {}, FakeCache())
    res = await mcp.tools["get_neighbors"](
        node_id="function:src/alpha_fn.py:alpha_fn:1", project="missing"
    )
    assert res["ok"] is False
    assert "missing" in res["message"]


@pytest.mark.asyncio
async def test_get_neighbors_project_arg_routes(pool: DBPool) -> None:
    mcp = FakeMCP()
    graph_tool.register(mcp, pool, {}, FakeCache())
    # alpha_fn exists only in alpha.db; querying with project="alpha" must succeed
    res = await mcp.tools["get_neighbors"](
        node_id="function:src/alpha_fn.py:alpha_fn:1", project="alpha"
    )
    assert res["ok"] is True

    # In beta.db there is no node with that id — neighbors traversal returns empty list
    res2 = await mcp.tools["get_neighbors"](
        node_id="function:src/alpha_fn.py:alpha_fn:1", project="beta"
    )
    assert res2["ok"] is True
    assert res2["data"] == []
