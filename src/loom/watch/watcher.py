from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterable, Awaitable, Callable, Protocol

from watchfiles import Change, awatch

from loom.core import LoomGraph, EdgeType
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.ingest.utils import (
    delete_nodes_by_ids,
    get_node_ids_by_path,
    invalidate_edges_for_file,
    mark_human_edges_stale_for_node,
    node_has_human_edges,
)
from loom.ingest.pipeline import index_repo


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


WatcherFactory = Callable[[str], AsyncIterable[set[tuple[Change, str]]]]
Indexer = Callable[[str, LoomGraph | _Graph], Awaitable[object]]


async def _default_indexer(repo_path: str, graph: LoomGraph | _Graph) -> object:
    return await index_repo(repo_path, graph)


async def _flag_changed_loom_edges(graph: LoomGraph | _Graph, *, path: str) -> None:
    loom_impl_rel = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)
    await graph.query(
        f"""
MATCH (n {{path: $path}})-[r:{loom_impl_rel}]->()
SET r.stale = true,
    r.stale_reason = 'source_changed'
""",
        {"path": path},
    )
    await graph.query(
        f"""
MATCH ()-[r:{loom_impl_rel}]->(n {{path: $path}})
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
            await _flag_changed_loom_edges(graph, path=path)
            await invalidate_edges_for_file(graph, path=path)
            ids = await get_node_ids_by_path(graph, path=path)
            preserved: list[str] = []
            for node_id in ids:
                if await node_has_human_edges(graph, node_id=node_id):
                    preserved.append(node_id)
                    await mark_human_edges_stale_for_node(graph, node_id=node_id, reason="file_deleted")
            deletable = [node_id for node_id in ids if node_id not in set(preserved)]
            await delete_nodes_by_ids(graph, deletable)

        if changed_paths - deleted_paths:
            for path in sorted(changed_paths - deleted_paths):
                await _flag_changed_loom_edges(graph, path=path)
            await indexer(repo_path, graph)

        processed += len(changes)
        if stop_after_events is not None and processed >= stop_after_events:
            return
