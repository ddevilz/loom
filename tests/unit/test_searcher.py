from __future__ import annotations

from pathlib import Path

import pytest

<<<<<<< HEAD
from loom.core import LoomGraph, Node, NodeKind, NodeSource
from loom.query.search import SearchResult, search


@pytest.mark.asyncio
async def test_search_returns_matching_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
        Node(
            id="function:src/a.py:authenticate",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="authenticate",
            path="src/a.py",
            language="python",
            metadata={},
        ),
        Node(
            id="function:src/a.py:authorize",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="authorize",
            path="src/a.py",
            language="python",
            metadata={},
        ),
    ])

    results = await search("authenticate", g, limit=5)
    assert isinstance(results, list)
    ids = [r.node.id for r in results]
    assert "function:src/a.py:authenticate" in ids


@pytest.mark.asyncio
async def test_search_returns_search_result_with_score(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
        Node(
            id="function:src/a.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
    ])

    results = await search("foo", g, limit=5)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.node.name == "foo"
    assert r.score == 1.0


@pytest.mark.asyncio
async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    results = await search("xyzzy_no_match", g, limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_respects_limit(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
        Node(
            id=f"function:src/a.py:func_{i}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"func_{i}",
            path="src/a.py",
            language="python",
            metadata={},
        )
        for i in range(20)
    ])

    results = await search("func", g, limit=3)
    assert len(results) <= 3
=======
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
        node = _row_to_node(
            {
                "kind": "function",
                "name": "f",
                "summary": "s",
                "path": "x",
                "metadata": {},
            }
        )

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
>>>>>>> main
