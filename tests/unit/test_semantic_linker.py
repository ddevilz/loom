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
