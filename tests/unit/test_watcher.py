from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from watchfiles import Change

from loom.watch.watcher import watch_repo


@dataclass
class _FakeGraph:
    queries: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    async def query(self, cypher: str, params: dict[str, Any] | None = None):
        self.queries.append((cypher, params))
        return []


@pytest.mark.asyncio
async def test_watch_repo_reindexes_on_file_change(tmp_path: Path) -> None:
    seen: list[str] = []

    async def fake_events(_path: str):
        yield {(Change.modified, str(tmp_path / "a.py"))}

    async def fake_indexer(repo_path: str, graph) -> object:
        seen.append(repo_path)
        return object()

    graph = _FakeGraph()
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        indexer=fake_indexer,
        stop_after_events=1,
    )

    assert seen == [str(tmp_path)]
    assert any("LOOM_IMPLEMENTS" in q[0] for q in graph.queries)


@pytest.mark.asyncio
async def test_watch_repo_deletes_nodes_on_removed_file(tmp_path: Path) -> None:
    async def fake_events(_path: str):
        yield {(Change.deleted, str(tmp_path / "gone.py"))}

    graph = _FakeGraph()
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        stop_after_events=1,
    )

    assert any("DETACH DELETE" in q[0] for q in graph.queries)
