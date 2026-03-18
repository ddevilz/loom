from __future__ import annotations

import pytest

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.search.searcher import _row_to_node, search


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _FakeGraph:
    async def query(self, cypher: str, params=None):
        return [
            {
                "id": "function:x:f",
                "kind": "function",
                "name": "f",
                "summary": "authentication flow",
                "path": "x",
                "metadata": {},
                "embedding": [1.0, 0.0],
            }
        ]

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind=None,
    ):
        return [
            Node(
                id="doc:spec:s1",
                kind=NodeKind.SECTION,
                source=NodeSource.DOC,
                name="Auth spec",
                path="spec",
                summary="authentication requirements",
                metadata={},
            )
        ]


@pytest.mark.asyncio
async def test_search_returns_ranked_results_with_graph_expansion() -> None:
    results = await search(
        "authentication", _FakeGraph(), limit=5, embedder=_FakeEmbedder()
    )
    assert results
    assert results[0].node.id == "function:x:f"
    assert any(r.matched_via == "graph" for r in results)


class _MultiBaseGraph:
    async def query(self, cypher: str, params=None):
        return [
            {
                "id": "function:x:f1",
                "kind": "function",
                "name": "f1",
                "summary": "authentication flow one",
                "path": "x",
                "metadata": {},
                "embedding": [1.0, 0.0],
                "score": 0.6,
            },
            {
                "id": "function:x:f2",
                "kind": "function",
                "name": "f2",
                "summary": "authentication flow two",
                "path": "x",
                "metadata": {},
                "embedding": [1.0, 0.0],
                "score": 0.9,
            },
        ]

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind=None,
    ):
        return [
            Node(
                id="doc:spec:s1",
                kind=NodeKind.SECTION,
                source=NodeSource.DOC,
                name="Auth spec",
                path="spec",
                summary="authentication requirements",
                metadata={},
            )
        ]


@pytest.mark.asyncio
async def test_search_graph_dedupe_keeps_highest_scoring_expansion() -> None:
    results = await search(
        "authentication", _MultiBaseGraph(), limit=5, embedder=_FakeEmbedder()
    )

    graph_results = [result for result in results if result.node.id == "doc:spec:s1"]

    assert len(graph_results) == 1
    assert graph_results[0].matched_via == "graph"
    assert graph_results[0].score == pytest.approx(0.9 * 0.85)


def test_row_to_node_returns_none_for_missing_id(caplog) -> None:
    """A row with no id must return None and log a warning, not return a stub node."""
    import logging

    with caplog.at_level(logging.WARNING, logger="loom.search.searcher"):
        node = _row_to_node({"kind": "function", "name": "f", "summary": "s", "path": "x", "metadata": {}})

    assert node is None, "Expected None for row with missing id, got a stub node"


def test_row_to_node_falls_back_for_invalid_doc_kind() -> None:
    node = _row_to_node(
        {
            "id": "doc:spec:s1",
            "kind": "not_a_kind",
            "name": "Spec",
            "summary": "s",
            "path": "spec",
            "metadata": {},
        }
    )

    assert node.kind == NodeKind.SECTION
    assert node.source == NodeSource.DOC


def test_row_to_node_uses_safe_name_and_path_fallbacks() -> None:
    node = _row_to_node(
        {"id": "function:x:f", "kind": "function", "summary": "s", "metadata": {}}
    )

    assert node.name == "function:x:f"
    assert node.path == ""


def test_row_to_node_decodes_json_metadata() -> None:
    node = _row_to_node(
        {
            "id": "function:x:f",
            "kind": "function",
            "name": "f",
            "summary": "s",
            "path": "x",
            "metadata": '{"owner": "team-a"}',
        }
    )

    assert node.metadata == {"owner": "team-a"}


def test_row_to_node_preserves_module_kind_for_module_ids() -> None:
    node = _row_to_node(
        {
            "id": "module:x:m",
            "kind": "module",
            "name": "m",
            "summary": "s",
            "path": "x",
            "metadata": {},
        }
    )

    assert node.kind == NodeKind.MODULE
    assert node.source == NodeSource.CODE


def test_row_to_node_falls_back_for_missing_code_kind() -> None:
    node = _row_to_node(
        {"id": "function:x:f", "name": "f", "summary": "s", "path": "x", "metadata": {}}
    )

    assert node.kind == NodeKind.FUNCTION
    assert node.source == NodeSource.CODE
