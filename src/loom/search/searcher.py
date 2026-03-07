from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.embed.embedder import FastEmbedder, Embedder, cosine_similarity

logger = logging.getLogger(__name__)


_QUERY_CANDIDATES = (
    "CALL db.idx.vector.queryNodes('Node', 'embedding', $k, vecf32($vec)) "
    "YIELD node, score "
    "WHERE node.summary IS NOT NULL "
    "RETURN node.id AS id, node.kind AS kind, node.name AS name, node.summary AS summary, "
    "node.path AS path, node.metadata AS metadata, score"
)

# Fallback query with LIMIT to prevent loading entire graph into memory
# This is a degraded mode when vector index is unavailable
_QUERY_CANDIDATES_FALLBACK = (
    "MATCH (n) WHERE n.summary IS NOT NULL AND n.embedding IS NOT NULL "
    "RETURN n.id AS id, n.kind AS kind, n.name AS name, n.summary AS summary, "
    "n.path AS path, n.metadata AS metadata, n.embedding AS embedding "
    "LIMIT $limit"
)


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind: NodeKind | None = None,
    ) -> list[Node]: ...


@dataclass(frozen=True)
class SearchResult:
    node: Node
    score: float
    matched_via: str


def _row_to_node(row: dict[str, Any]) -> Node:
    kind = row.get("kind")
    kind_value = kind.value if hasattr(kind, "value") else str(kind)
    node_id = str(row.get("id"))
    source = NodeSource.DOC if node_id.startswith("doc:") else NodeSource.CODE
    return Node(
        id=node_id,
        kind=NodeKind(kind_value),
        source=source,
        name=str(row.get("name")),
        summary=row.get("summary"),
        path=str(row.get("path")),
        embedding=row.get("embedding") if isinstance(row.get("embedding"), list) else None,
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


async def search(
    query_text: str,
    graph: _Graph,
    *,
    limit: int = 10,
    expand_depth: int = 1,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    if embedder is None:
        embedder = FastEmbedder()

    query_vector = (await asyncio.to_thread(embedder.embed, [query_text]))[0]
    try:
        rows = await graph.query(_QUERY_CANDIDATES, {"k": limit * 3, "vec": query_vector})
        base = [
            SearchResult(node=_row_to_node(row), score=float(row.get("score", 0.0)), matched_via="vector")
            for row in rows
            if row.get("id") is not None
        ][:limit]
    except Exception as e:
        # Vector index query failed - fall back to brute force search
        logger.warning(
            f"Vector index query failed: {e}. Falling back to brute-force similarity search. "
            "This is significantly slower. Consider checking vector index health."
        )
        # Limit fallback to prevent memory exhaustion on large graphs
        fallback_limit = min(limit * 100, 10000)
        rows = await graph.query(_QUERY_CANDIDATES_FALLBACK, {"limit": fallback_limit})
        
        if len(rows) >= fallback_limit:
            logger.warning(
                f"Fallback search hit limit of {fallback_limit} nodes. "
                "Results may be incomplete. Vector index is recommended for large graphs."
            )
        
        nodes = [_row_to_node(row) for row in rows]
        scored: list[SearchResult] = []
        for node in nodes:
            if node.embedding is None:
                continue
            score = cosine_similarity(query_vector, node.embedding)
            if score <= 0.0:
                continue
            scored.append(SearchResult(node=node, score=score, matched_via="vector_fallback"))
        scored.sort(key=lambda r: r.score, reverse=True)
        base = scored[:limit]

    expanded: dict[str, SearchResult] = {r.node.id: r for r in base}
    if base:
        neighbor_batches = await asyncio.gather(
            *[
                graph.neighbors(
                    res.node.id,
                    depth=expand_depth,
                    edge_types=[EdgeType.CALLS, EdgeType.LOOM_IMPLEMENTS],
                )
                for res in base
            ]
        )
        for res, neighbors in zip(base, neighbor_batches, strict=False):
            for neighbor in neighbors:
                score = res.score * 0.85
                candidate = SearchResult(node=neighbor, score=score, matched_via="graph")
                if neighbor.id not in expanded:
                    expanded[neighbor.id] = candidate

    return sorted(expanded.values(), key=lambda r: r.score, reverse=True)[:limit]
