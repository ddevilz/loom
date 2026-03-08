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


class _FakeSummaryLLM:
    async def summarize(self, *, prompt: str, max_tokens: int = 200, model: str | None = None) -> str:
        return "hashes password with bcrypt"


@pytest.mark.asyncio
async def test_semantic_linker_persists_cross_domain_edges() -> None:
    code = Node(
        id="function:x:hash_pw",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="hash_pw",
        path="x",
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
    code = code.model_copy(update={"summary": "hashes password with bcrypt", "embedding": [1.0, 0.0]})

    graph = _FakeGraph()
    linker = SemanticLinker(summary_llm=_FakeSummaryLLM())
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
async def test_semantic_linker_allows_later_tier_to_link_second_code_to_same_doc(monkeypatch) -> None:
    code1 = Node(id="function:x:f1", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="f1", path="x", metadata={})
    code2 = Node(id="function:x:f2", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="f2", path="x", metadata={})
    doc = Node(id="doc:spec.md:s1", kind=NodeKind.SECTION, source=NodeSource.DOC, name="Spec", path="spec.md", metadata={})

    tier1_edge = Edge(
        from_id=code1.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.NAME_MATCH,
        confidence=0.8,
        link_method="name_match",
        link_reason="tier1",
        metadata={},
    )
    tier2_edge = Edge(
        from_id=code2.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.EMBED_MATCH,
        confidence=0.85,
        link_method="embed_match",
        link_reason="tier2",
        metadata={},
    )

    monkeypatch.setattr("loom.linker.linker.link_by_name", lambda code_nodes, doc_nodes, threshold=0.6: [tier1_edge])

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold=0.75, graph=None):
        assert [node.id for node in code_nodes] == [code1.id, code2.id]
        assert [node.id for node in doc_nodes] == [doc.id]
        return [tier2_edge]

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    graph = _FakeGraph()
    linker = SemanticLinker()

    edges = await linker.link([code1, code2], [doc], graph)

    assert {(edge.from_id, edge.to_id) for edge in edges} == {
        (code1.id, doc.id),
        (code2.id, doc.id),
    }


@pytest.mark.asyncio
async def test_semantic_linker_llm_fallback_can_link_same_code_to_second_doc(monkeypatch) -> None:
    code = Node(id="function:x:f", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="f", path="x", metadata={})
    doc1 = Node(id="doc:spec.md:s1", kind=NodeKind.SECTION, source=NodeSource.DOC, name="Spec 1", path="spec.md", metadata={})
    doc2 = Node(id="doc:spec.md:s2", kind=NodeKind.SECTION, source=NodeSource.DOC, name="Spec 2", path="spec.md", metadata={})

    tier1_edge = Edge(
        from_id=code.id,
        to_id=doc1.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.NAME_MATCH,
        confidence=0.8,
        link_method="name_match",
        link_reason="tier1",
        metadata={},
    )
    tier3_edge = Edge(
        from_id=code.id,
        to_id=doc2.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.LLM_MATCH,
        confidence=0.9,
        link_method="llm_match",
        link_reason="tier3",
        metadata={},
    )

    monkeypatch.setattr("loom.linker.linker.link_by_name", lambda code_nodes, doc_nodes, threshold=0.6: [tier1_edge])

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold=0.75, graph=None):
        return []

    async def _fake_link_by_llm(code_nodes, doc_nodes, *, llm, threshold=0.6):
        assert [node.id for node in code_nodes] == [code.id]
        assert [node.id for node in doc_nodes] == [doc1.id, doc2.id]
        return [tier3_edge]

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)
    monkeypatch.setattr("loom.linker.linker.link_by_llm", _fake_link_by_llm)

    graph = _FakeGraph()
    linker = SemanticLinker(llm_fallback=True, match_llm=object())

    edges = await linker.link([code], [doc1, doc2], graph)

    assert {(edge.from_id, edge.to_id) for edge in edges} == {
        (code.id, doc1.id),
        (code.id, doc2.id),
    }
