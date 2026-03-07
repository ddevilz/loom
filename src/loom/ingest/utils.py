from __future__ import annotations

from typing import Any, Protocol


_DELETE_NON_HUMAN_EDGES_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin IS NULL OR r.origin <> 'human'
DELETE r
"""

_MARK_HUMAN_EDGES_STALE_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = 'source_changed'
"""


class EdgeInvalidationGraph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


async def invalidate_edges_for_file(graph: EdgeInvalidationGraph, *, path: str) -> None:
    await graph.query(_DELETE_NON_HUMAN_EDGES_FOR_FILE, {"path": path})
    await graph.query(_MARK_HUMAN_EDGES_STALE_FOR_FILE, {"path": path})
