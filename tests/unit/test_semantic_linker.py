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
async def test_semantic_linker_persists_cross_domain_edges(monkeypatch) -> None:
    code = Node(
        id="function:x:hash_pw",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="hash_pw",
        path="x",
        summary="hashes password with bcrypt",
        embedding=[1.0, 0.0],
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Password policy",
        path="spec.md",
        summary="Passwords must be hashed before storage.",
        embedding=[1.0, 0.0],
        metadata={},
    )

    expected_edge = Edge(
        from_id=code.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.EMBED_MATCH,
        confidence=1.0,
        link_method="embed_match",
        link_reason="cosine=1.000",
        metadata={},
    )

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold, graph):
        return [expected_edge]

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    graph = _FakeGraph()
    linker = SemanticLinker()
    edges = await linker.link([code], [doc], graph)

    assert edges
    assert graph.persisted
    assert graph.persisted[0].from_id == code.id
    assert graph.persisted[0].to_id == doc.id


def test_semantic_linker_dedupe_preserves_human_edge() -> None:
    human_edge = Edge(
        from_id="function:x:f",
        to_id="doc:spec.md:s1",
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.HUMAN,
        confidence=0.75,
        metadata={},
    )
    machine_edge = Edge(
        from_id="function:x:f",
        to_id="doc:spec.md:s1",
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.EMBED_MATCH,
        confidence=0.95,
        link_method="embed_match",
        link_reason="cosine=0.950",
        metadata={},
    )

    deduped = SemanticLinker._dedupe_edges([machine_edge, human_edge])

    assert len(deduped) == 1
    assert deduped[0].origin == EdgeOrigin.HUMAN
    assert deduped[0].confidence == 0.75


@pytest.mark.asyncio
async def test_semantic_linker_allows_embed_to_link_multiple_code_to_same_doc(
    monkeypatch,
) -> None:
    code1 = Node(
        id="function:x:f1",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f1",
        path="x",
        metadata={},
    )
    code2 = Node(
        id="function:x:f2",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f2",
        path="x",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Spec",
        path="spec.md",
        metadata={},
    )

    edge1 = Edge(
        from_id=code1.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.EMBED_MATCH,
        confidence=0.8,
        link_method="embed_match",
        link_reason="cosine=0.800",
        metadata={},
    )
    edge2 = Edge(
        from_id=code2.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.EMBED_MATCH,
        confidence=0.85,
        link_method="embed_match",
        link_reason="cosine=0.850",
        metadata={},
    )

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold, graph=None):
        return [edge1, edge2]

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    graph = _FakeGraph()
    linker = SemanticLinker()

    edges = await linker.link([code1, code2], [doc], graph)

    assert {(edge.from_id, edge.to_id) for edge in edges} == {
        (code1.id, doc.id),
        (code2.id, doc.id),
    }


@pytest.mark.asyncio
async def test_semantic_linker_returns_empty_when_no_edges(monkeypatch) -> None:
    code = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Spec",
        path="spec.md",
        metadata={},
    )

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold, graph=None):
        return []

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    graph = _FakeGraph()
    linker = SemanticLinker()

    edges = await linker.link([code], [doc], graph)

    assert edges == []
    assert graph.persisted == []
