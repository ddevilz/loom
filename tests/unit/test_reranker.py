from __future__ import annotations

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.linker.reranker import rerank_edges


class _FakeReranker:
    def __init__(self, scores: dict[tuple[str, str], float]) -> None:
        self.scores = scores

    def rerank(self, code_node: Node, doc_node: Node) -> float:
        return self.scores[(code_node.id, doc_node.id)]


def test_rerank_edges_sorts_and_filters_candidates() -> None:
    code_nodes = [
        Node(
            id="function:x:a",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="a",
            path="x",
            metadata={},
        ),
        Node(
            id="function:x:b",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="b",
            path="x",
            metadata={},
        ),
    ]
    doc_nodes = [
        Node(
            id="doc:s:1",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="1",
            path="s",
            metadata={},
        ),
        Node(
            id="doc:s:2",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="2",
            path="s",
            metadata={},
        ),
    ]
    edges = [
        Edge(
            from_id="function:x:a",
            to_id="doc:s:1",
            kind=EdgeType.LOOM_IMPLEMENTS,
            origin=EdgeOrigin.EMBED_MATCH,
            confidence=0.8,
            link_method="embed_match",
            link_reason="cosine=0.8",
            metadata={},
        ),
        Edge(
            from_id="function:x:b",
            to_id="doc:s:2",
            kind=EdgeType.LOOM_IMPLEMENTS,
            origin=EdgeOrigin.EMBED_MATCH,
            confidence=0.7,
            link_method="embed_match",
            link_reason="cosine=0.7",
            metadata={},
        ),
    ]

    reranked = rerank_edges(
        edges,
        code_nodes=code_nodes,
        doc_nodes=doc_nodes,
        reranker=_FakeReranker(
            {("function:x:a", "doc:s:1"): 0.2, ("function:x:b", "doc:s:2"): 0.9}
        ),
        threshold=0.3,
    )

    assert len(reranked) == 1
    assert reranked[0].from_id == "function:x:b"
    assert reranked[0].confidence == 0.9
