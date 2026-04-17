from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.linker.linker import SemanticLinker


@dataclass
class _FakeGraph:
    persisted: list[Edge] = field(default_factory=list)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        self.persisted.extend(edges)


@pytest.mark.asyncio
async def test_semantic_linker_uses_embed_threshold(monkeypatch) -> None:
    """SemanticLinker passes the configured threshold to link_by_embedding."""
    code = Node(
        id="function:x:target",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="target",
        path="x",
        summary="hash password",
        embedding=[1.0, 0.0],
        metadata={},
    )
    doc = Node(
        id="doc:s:1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Requirement",
        path="s",
        summary="password hashing requirement",
        embedding=[1.0, 0.0],
        metadata={},
    )

    captured_threshold: list[float] = []

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold, graph=None):
        captured_threshold.append(threshold)
        return [
            Edge(
                from_id=code.id,
                to_id=doc.id,
                kind=EdgeType.LOOM_IMPLEMENTS,
                origin=EdgeOrigin.EMBED_MATCH,
                confidence=0.95,
                link_method="embed_match",
                link_reason="cosine=0.950",
                metadata={},
            )
        ]

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    graph = _FakeGraph()
    linker = SemanticLinker(embedding_threshold=0.9)
    edges = await linker.link([code], [doc], graph)

    assert edges
    assert captured_threshold == [0.9]
