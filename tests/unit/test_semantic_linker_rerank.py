from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from loom.core import Edge, Node, NodeKind, NodeSource
from loom.linker.linker import SemanticLinker


@dataclass
class _FakeGraph:
    persisted: list[Edge] = field(default_factory=list)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        self.persisted.extend(edges)


class _FakeReranker:
    def rerank(self, code_node: Node, doc_node: Node) -> float:
        return 0.95 if code_node.name == "target" else 0.1


@pytest.mark.asyncio
async def test_semantic_linker_uses_reranker_for_tier2_candidates() -> None:
    code = Node(id="function:x:target", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="target", path="x", summary="hash password", embedding=[1.0, 0.0], metadata={})
    doc = Node(id="doc:s:1", kind=NodeKind.SECTION, source=NodeSource.DOC, name="Requirement", path="s", summary="password hashing requirement", embedding=[1.0, 0.0], metadata={})

    graph = _FakeGraph()
    linker = SemanticLinker(reranker=_FakeReranker(), rerank_threshold=0.5)
    edges = await linker.link([code], [doc], graph)

    assert edges
    assert edges[0].confidence == 0.95
    assert "cross_encoder" in (edges[0].link_reason or "")
