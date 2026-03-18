from __future__ import annotations

import logging

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.core.protocols import QueryGraph
from loom.embed.embedder import cosine_similarity, embed_nodes

logger = logging.getLogger(__name__)

_VECTOR_K_LIMIT = 50
_FALLBACK_DOC_CANDIDATE_LIMIT = 1000


_VECTOR_CANDIDATES_QUERY = (
    "CALL db.idx.vector.queryNodes('Node', 'embedding', $k, vecf32($vec)) "
    "YIELD node, score "
    "WHERE node.id STARTS WITH 'doc:' "
    "RETURN node.id AS id, score"
)


async def _candidate_doc_ids_from_vector_index(
    code_node: Node,
    doc_by_id: dict[str, Node],
    graph: QueryGraph,
) -> list[str] | None:
    if code_node.embedding is None:
        return []
    try:
        rows = await graph.query(
            _VECTOR_CANDIDATES_QUERY,
            {
                "k": min(max(10, len(doc_by_id)), _VECTOR_K_LIMIT),
                "vec": code_node.embedding,
            },
        )
    except Exception as exc:
        logger.warning(
            "Vector index query failed for node %r: %s. Falling back to full doc scan.",
            code_node.id,
            exc,
        )
        return None
    return [
        row["id"]
        for row in rows
        if isinstance(row.get("id"), str) and row["id"] in doc_by_id
    ]


async def link_by_embedding(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    *,
    threshold: float = 0.75,
    graph: QueryGraph | None = None,
) -> list[Edge]:
    # Ensure embeddings exist where possible. embed_nodes is idempotent — it skips
    # nodes that already have an embedding set, so callers that pre-embed (e.g.
    # incremental.py/_finalize_upsert_nodes) pay no extra cost here.
    code_nodes = await embed_nodes(code_nodes)
    doc_nodes = await embed_nodes(doc_nodes)

    edges: list[Edge] = []
    doc_by_id = {node.id: node for node in doc_nodes}

    for c in code_nodes:
        if c.embedding is None:
            continue
        candidate_doc_ids = None
        if graph is not None:
            candidate_doc_ids = await _candidate_doc_ids_from_vector_index(
                c, doc_by_id, graph
            )
        candidate_docs = (
            [doc_by_id[doc_id] for doc_id in candidate_doc_ids]
            if candidate_doc_ids is not None
            else list(doc_by_id.values())[:_FALLBACK_DOC_CANDIDATE_LIMIT]
        )
        for d in candidate_docs:
            if d.embedding is None:
                continue
            score = cosine_similarity(c.embedding, d.embedding)
            if score < threshold:
                continue
            edges.append(
                Edge(
                    from_id=c.id,
                    to_id=d.id,
                    kind=EdgeType.LOOM_IMPLEMENTS,
                    origin=EdgeOrigin.EMBED_MATCH,
                    confidence=float(score),
                    link_method="embed_match",
                    link_reason=f"cosine={score:.3f}",
                    metadata={},
                )
            )

    return edges
