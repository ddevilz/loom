from __future__ import annotations

from dataclasses import dataclass

from loom.core.graph import LoomGraph
from loom.core.node import Node


@dataclass
class SearchResult:
    node: Node
    score: float


async def search(
    query: str, graph: LoomGraph, *, limit: int = 10
) -> list[SearchResult]:
    """Search for nodes by name prefix or FTS5 full-text."""
    nodes = await graph.search(query, limit=limit)
    return [SearchResult(node=n, score=1.0) for n in nodes]
