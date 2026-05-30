"""End-to-end: index two repos, boot server primed on repo_a, search repo_b by name."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastmcp import Client

from loom.graph.db import DB
from loom.graph.projects import ProjectRegistry
from loom.server.app import build_server


def _seed(db: DB, fn_name: str) -> None:
    conn = db.connect()
    now = int(time.time())
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, start_line, end_line, "
        "language, content_hash, summary, summary_hash, token_count, metadata, "
        "updated_at, deleted_at) "
        "VALUES (?, 'function', 'code', ?, ?, 1, 2, 'python', 'h', NULL, NULL, "
        "10, '{}', ?, NULL)",
        (
            f"function:src/{fn_name}.py:{fn_name}:1",
            fn_name,
            f"src/{fn_name}.py",
            now,
        ),
    )
    conn.commit()


def _install_registry_in_dir(monkeypatch: pytest.MonkeyPatch, pdir: Path) -> None:
    """Make ProjectRegistry() default to ``pdir`` for the duration of the test.

    The class default arg is bound at definition time, so patching the module-
    level ``_DEFAULT_PROJECTS_DIR`` alone is insufficient. We also replace
    ``ProjectRegistry`` with a subclass whose no-arg ``__init__`` points at
    ``pdir``, which is what ``build_server`` constructs.
    """
    import loom.graph.projects as projects_mod

    monkeypatch.setattr(projects_mod, "_DEFAULT_PROJECTS_DIR", pdir)

    class _TempRegistry(ProjectRegistry):
        def __init__(self, projects_dir: Path = pdir) -> None:  # noqa: B008
            super().__init__(projects_dir=projects_dir)

    monkeypatch.setattr(projects_mod, "ProjectRegistry", _TempRegistry)


@pytest.mark.asyncio
async def test_cross_project_search_via_project_arg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    repo_a = DB(path=pdir / "repo_a.db")
    repo_b = DB(path=pdir / "repo_b.db")
    _seed(repo_a, "fn_in_a")
    _seed(repo_b, "fn_in_b")
    repo_a.close()
    repo_b.close()

    _install_registry_in_dir(monkeypatch, pdir)

    # Boot server primed against repo_a
    boot = DB(path=pdir / "repo_a.db")
    boot.connect()
    server = build_server(db=boot)

    async with Client(server) as client:
        # Default (no project=) routes to primed repo_a
        ra = await client.call_tool("search_code", {"query": "fn_in_a"})
        names_a = [r["name"] for r in ra.data["data"]]
        assert "fn_in_a" in names_a
        assert "fn_in_b" not in names_a

        # Explicit project="repo_b" routes via registry to repo_b.db
        rb = await client.call_tool(
            "search_code", {"query": "fn_in_b", "project": "repo_b"}
        )
        names_b = [r["name"] for r in rb.data["data"]]
        assert "fn_in_b" in names_b
        assert "fn_in_a" not in names_b

        # Unknown project returns validation error
        rx = await client.call_tool(
            "search_code", {"query": "x", "project": "nope"}
        )
        assert rx.data["ok"] is False
        assert "nope" in rx.data["message"]


@pytest.mark.asyncio
async def test_list_projects_reports_indexed_dbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    a = DB(path=pdir / "alpha.db")
    b = DB(path=pdir / "beta.db")
    _seed(a, "fn_alpha")
    _seed(b, "fn_beta")
    a.close()
    b.close()

    _install_registry_in_dir(monkeypatch, pdir)

    boot = DB(path=pdir / "alpha.db")
    boot.connect()
    server = build_server(db=boot)

    async with Client(server) as client:
        r = await client.call_tool("list_projects", {})
        data = r.data["data"]
        names = sorted(p["name"] for p in data["projects"])
        assert names == ["alpha", "beta"]
        # Each entry must include name/path/db_size_bytes/node_count/last_indexed
        first = data["projects"][0]
        assert set(first) >= {
            "name",
            "path",
            "db_size_bytes",
            "node_count",
            "last_indexed",
        }
        assert first["node_count"] >= 1
