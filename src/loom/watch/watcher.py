from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterable, Awaitable, Callable, Protocol

from watchfiles import Change, awatch

from loom.core import LoomGraph
from loom.ingest.pipeline import index_repo


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


WatcherFactory = Callable[[str], AsyncIterable[set[tuple[Change, str]]]]
Indexer = Callable[[str, LoomGraph | _Graph], Awaitable[object]]


async def _default_indexer(repo_path: str, graph: LoomGraph | _Graph) -> object:
    return await index_repo(repo_path, graph)


async def _delete_nodes_by_path(graph: LoomGraph | _Graph, *, path: str) -> None:
    await graph.query("MATCH (n {path: $path}) DETACH DELETE n", {"path": path})


async def _flag_changed_loom_edges(graph: LoomGraph | _Graph, *, path: str) -> None:
    await graph.query(
        """
MATCH (n {path: $path})-[r:LOOM_IMPLEMENTS]->()
SET r.stale = true,
    r.stale_reason = 'source_changed'
""",
        {"path": path},
    )


def _watch_stream(repo_path: str, *, debounce_ms: int) -> AsyncIterable[set[tuple[Change, str]]]:
    return awatch(repo_path, debounce=debounce_ms)


async def watch_repo(
    repo_path: str,
    graph: LoomGraph | _Graph,
    *,
    debounce_ms: int = 500,
    watcher_factory: WatcherFactory | None = None,
    indexer: Indexer | None = None,
    stop_after_events: int | None = None,
) -> None:
    watcher = watcher_factory or (lambda path: _watch_stream(path, debounce_ms=debounce_ms))
    indexer = indexer or _default_indexer

    processed = 0
    async for changes in watcher(repo_path):
        changed_paths = {Path(path).resolve().as_posix() for _, path in changes}
        deleted_paths = {
            Path(path).resolve().as_posix()
            for change, path in changes
            if change == Change.deleted
        }

        for path in sorted(deleted_paths):
            await _delete_nodes_by_path(graph, path=path)
            await _flag_changed_loom_edges(graph, path=path)

        if changed_paths - deleted_paths:
            await indexer(repo_path, graph)
            for path in sorted(changed_paths - deleted_paths):
                await _flag_changed_loom_edges(graph, path=path)

        processed += len(changes)
        if stop_after_events is not None and processed >= stop_after_events:
            return
