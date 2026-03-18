from __future__ import annotations

import logging

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
async def test_llm_fallback_true_but_no_llm_emits_warning(caplog) -> None:
    """When llm_fallback=True but match_llm is None, a WARNING must be emitted."""
    linker = SemanticLinker(llm_fallback=True, match_llm=None)

    with caplog.at_level(logging.WARNING, logger="loom.linker.linker"):
        await linker.link(
            [_make_code_node("foo")],
            [_make_doc_node("bar")],
            _FakeGraph(),
        )

    warning_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("llm_fallback" in m for m in warning_messages), (
        "Expected a WARNING when llm_fallback=True but match_llm is None; got none"
    )
