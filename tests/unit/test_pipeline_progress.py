from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loom.graph.db import DB
from loom.graph.repository import Repository
from loom.indexer.pipeline import index_repo


@pytest.fixture
def db(tmp_path: Path) -> DB:
    return DB(path=tmp_path / "test.db")


@pytest.mark.asyncio
async def test_progress_cb_called_during_index(tmp_path: Path, db: DB) -> None:
    """progress_cb receives phase/done/total updates during index_repo."""
    calls: list[dict[str, Any]] = []

    def cb(phase: str, done: int, total: int) -> None:
        calls.append({"phase": phase, "done": done, "total": total})

    await index_repo(tmp_path, Repository(db), progress_cb=cb)
    # Even on empty repo some phase callbacks fire
    # At minimum, indexing completes without error
    assert len(calls) > 0, "progress_cb should be called at least once"
    for c in calls:
        assert "phase" in c
        assert isinstance(c["done"], int)
        assert isinstance(c["total"], int)
        assert c["done"] >= 0


@pytest.mark.asyncio
async def test_index_repo_works_without_progress_cb(tmp_path: Path, db: DB) -> None:
    """progress_cb=None (default) — no error."""
    result = await index_repo(tmp_path, Repository(db))
    assert result is not None
