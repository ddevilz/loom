from __future__ import annotations

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.embed.embedder import cosine_similarity, embed_nodes


async def link_by_embedding(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    *,
    threshold: float = 0.75,
) -> list[Edge]:
    # Ensure embeddings exist where possible.
    code_nodes = await embed_nodes(code_nodes)
    doc_nodes = await embed_nodes(doc_nodes)

    edges: list[Edge] = []

    for c in code_nodes:
        if c.embedding is None:
            continue
        for d in doc_nodes:
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
