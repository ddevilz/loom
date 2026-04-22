from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import LoomGraph
from loom.ingest.pipeline import index_repo


@pytest.mark.asyncio
async def test_index_repo_parses_python_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")

    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await index_repo(tmp_path, g)

    assert result.files_parsed >= 1
    assert result.nodes_written >= 1

    stats = await g.stats()
    assert stats["nodes"] >= 1


@pytest.mark.asyncio
async def test_index_repo_skips_unchanged_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")

    g = LoomGraph(db_path=tmp_path / "loom.db")

    r1 = await index_repo(tmp_path, g)
    assert r1.files_parsed == 1
    assert r1.files_skipped == 0

    r2 = await index_repo(tmp_path, g)
    assert r2.files_parsed == 0
    assert r2.files_skipped == 1


@pytest.mark.asyncio
async def test_index_repo_with_real_markdown_doc(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "spec.md").write_text("# Auth\nThis is the spec.\n", encoding="utf-8")

    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await index_repo(tmp_path, g, docs_path=docs_dir)

    assert result.nodes_written >= 1
    stats = await g.stats()
    # Should have at least the function node + file node + some doc nodes
    assert stats["nodes"] >= 1
