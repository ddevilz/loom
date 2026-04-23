from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.ingest.pipeline import index_repo
from loom.query import traversal
from loom.store import nodes as node_store


def _write(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.asyncio
async def test_index_repo_parses_two_python_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "def g():\n    return 2\n")

    db = DB(path=tmp_path / "loom.db")
    r1 = await index_repo(tmp_path, db)

    assert r1.files_parsed == 2
    assert r1.files_skipped == 0
    assert r1.nodes_written >= 2

    s = await traversal.stats(db)
    assert s["nodes"] >= 2


@pytest.mark.asyncio
async def test_index_repo_skips_unchanged_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "def g():\n    return 2\n")

    db = DB(path=tmp_path / "loom.db")

    r1 = await index_repo(tmp_path, db)
    assert r1.files_parsed == 2
    assert r1.files_skipped == 0

    r2 = await index_repo(tmp_path, db)
    assert r2.files_parsed == 0
    assert r2.files_skipped == 2


@pytest.mark.asyncio
async def test_index_repo_updates_only_changed_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "def g():\n    return 2\n")

    db = DB(path=tmp_path / "loom.db")

    r1 = await index_repo(tmp_path, db)
    assert r1.files_parsed == 2

    a.write_text("def f():\n    return 99\n", encoding="utf-8")

    r2 = await index_repo(tmp_path, db)
    assert r2.files_parsed == 1
    assert r2.files_skipped == 1


@pytest.mark.asyncio
async def test_index_repo_replace_file_removes_old_nodes(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "def old_func():\n    pass\n")

    db = DB(path=tmp_path / "loom.db")
    await index_repo(tmp_path, db)

    old_nodes = await node_store.get_nodes_by_name(db, "old_func")
    assert len(old_nodes) == 1

    a.write_text("def new_func():\n    pass\n", encoding="utf-8")
    await index_repo(tmp_path, db)

    new_nodes = await node_store.get_nodes_by_name(db, "new_func")
    assert len(new_nodes) == 1

    gone_nodes = await node_store.get_nodes_by_name(db, "old_func")
    assert len(gone_nodes) == 0
