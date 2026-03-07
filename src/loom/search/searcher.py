from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.embed.embedder import FastEmbedder, Embedder, cosine_similarity


_QUERY_CANDIDATES = (
    "MATCH (n) WHERE n.summary IS NOT NULL "
    "RETURN n.id AS id, n.kind AS kind, n.name AS name, n.summary AS summary, n.path AS path, n.metadata AS metadata, n.embedding AS embedding"
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

    query_vector = embedder.embed([query_text])[0]
    rows = await graph.query(_QUERY_CANDIDATES)
    nodes = [_row_to_node(row) for row in rows]

    scored: list[SearchResult] = []
    for node in nodes:
        if node.embedding is None:
            continue
        score = cosine_similarity(query_vector, node.embedding)
        if score <= 0.0:
            continue
        scored.append(SearchResult(node=node, score=score, matched_via="vector"))

    scored.sort(key=lambda r: r.score, reverse=True)
    base = scored[:limit]

    expanded: dict[str, SearchResult] = {r.node.id: r for r in base}
    for res in base:
        neighbors = await graph.neighbors(
            res.node.id,
            depth=expand_depth,
            edge_types=[EdgeType.CALLS, EdgeType.LOOM_IMPLEMENTS],
        )
        for neighbor in neighbors:
            score = res.score * 0.85
            current = expanded.get(neighbor.id)
            candidate = SearchResult(node=neighbor, score=score, matched_via="graph")
            if current is None or candidate.score > current.score:
                expanded[neighbor.id] = candidate

    return sorted(expanded.values(), key=lambda r: r.score, reverse=True)[:limit]
