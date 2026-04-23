from __future__ import annotations

import pytest

from loom.core import Edge, Node, NodeKind, NodeSource
from loom.linker.linker import SemanticLinker


def _make_code_node(name: str) -> Node:
    return Node(
        id=f"function:x:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path="x.py",
        metadata={},
    )


def _make_doc_node(name: str) -> Node:
    return Node(
        id=f"doc:spec:{name}",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=name,
        path="spec.md",
        metadata={},
    )


class _FakeGraph:
    async def query(self, cypher: str, params=None):
        return []

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        pass

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        pass

    async def neighbors(self, node_id: str, depth: int = 1, edge_types=None, kind=None):
        return []


@pytest.mark.asyncio
async def test_semantic_linker_returns_no_edges_when_embed_match_empty(
    monkeypatch,
) -> None:
    """SemanticLinker returns empty list when embed match yields nothing."""

    async def _fake_link_by_embedding(code_nodes, doc_nodes, *, threshold, graph=None):
        return []

    monkeypatch.setattr("loom.linker.linker.link_by_embedding", _fake_link_by_embedding)

    linker = SemanticLinker()
    edges = await linker.link(
        [_make_code_node("foo")],
        [_make_doc_node("bar")],
        _FakeGraph(),
    )

    assert edges == []
