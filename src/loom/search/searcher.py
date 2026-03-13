from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.mappers import coerce_row_node_kind, row_to_node
from loom.embed.embedder import Embedder, FastEmbedder, cosine_similarity

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
    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...

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


def _coerce_node_kind(raw_kind: Any, *, fallback: NodeKind) -> NodeKind:
    return coerce_row_node_kind(raw_kind, fallback=fallback) or fallback


def _row_to_node(row: dict[str, Any]) -> Node:
    node_id = str(row.get("id"))
    source = NodeSource.DOC if node_id.startswith("doc:") else NodeSource.CODE
    fallback_kind = NodeKind.SECTION if source == NodeSource.DOC else NodeKind.FUNCTION
    return row_to_node(
        row,
        source=source,
        fallback_kind=_coerce_node_kind(row.get("kind"), fallback=fallback_kind),
        allow_embedding=True,
    ) or Node(
        id=node_id,
        kind=fallback_kind,
        source=source,
        name=node_id,
        path="",
        metadata={},
    )


async def search(
    query_text: str,
    graph: _Graph,
    *,
    limit: int = 10,
    expand_depth: int = 1,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    limit = max(1, min(limit, 100))
    expand_depth = max(0, min(expand_depth, 10))

    if embedder is None:
        embedder = FastEmbedder()

    query_vector = (await asyncio.to_thread(embedder.embed, [query_text]))[0]
    try:
        rows = await graph.query(
            _QUERY_CANDIDATES, {"k": limit * 3, "vec": query_vector}
        )
        base = [
            SearchResult(
                node=_row_to_node(row),
                score=float(row.get("score", 0.0)),
                matched_via="vector",
            )
            for row in rows[:limit]
            if row.get("id") is not None
        ]
    except Exception as e:
        # Vector index query failed - fall back to brute force search
        logger.warning(
            "Vector index query failed: %s. Falling back to brute-force similarity search.",
            e,
        )
        # Limit fallback to prevent memory exhaustion on large graphs
        fallback_limit = min(limit * 100, 10000)
        rows = await graph.query(_QUERY_CANDIDATES_FALLBACK, {"limit": fallback_limit})

        if len(rows) >= fallback_limit:
            logger.warning(
                "Fallback search hit limit of %d nodes. "
                "Results may be incomplete. Vector index is recommended for large graphs.",
                fallback_limit,
            )

        nodes = [_row_to_node(row) for row in rows]
        scored: list[SearchResult] = []
        for node in nodes:
            if node.embedding is None:
                continue
            score = cosine_similarity(query_vector, node.embedding)
            if score <= 0.0:
                continue
            scored.append(
                SearchResult(node=node, score=score, matched_via="vector_fallback")
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        base = scored[:limit]

    expanded: dict[str, SearchResult] = {r.node.id: r for r in base}
    if base:
        neighbor_batches = await asyncio.gather(
            *[
                graph.neighbors(
                    res.node.id,
                    depth=expand_depth,
                    edge_types=[
                        EdgeType.CALLS,
                        EdgeType.LOOM_IMPLEMENTS,
                        EdgeType.CONTAINS,
                    ],
                )
                for res in base
            ]
        )
        for res, neighbors in zip(base, neighbor_batches, strict=False):
            for neighbor in neighbors:
                score = res.score * 0.85
                candidate = SearchResult(
                    node=neighbor, score=score, matched_via="graph"
                )
                current = expanded.get(neighbor.id)
                if current is None or candidate.score > current.score:
                    expanded[neighbor.id] = candidate

    return sorted(expanded.values(), key=lambda r: r.score, reverse=True)[:limit]
