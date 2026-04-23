from __future__ import annotations

<<<<<<< HEAD
import pytest

from loom.core import LoomGraph, Node, NodeKind, NodeSource
from loom.query.node_lookup import (
    resolve_node_id,
)


@pytest.mark.asyncio
async def test_resolve_node_id_direct_id_passthrough(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await resolve_node_id(g, target="function:src/a.py:foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_single_match(tmp_path) -> None:
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
        )
    ])
    result = await resolve_node_id(g, target="foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_no_match_returns_none(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await resolve_node_id(g, target="no_such_function")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_ambiguous_returns_none(tmp_path) -> None:
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
        Node(
            id="function:src/b.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="src/b.py",
            language="python",
            metadata={},
        ),
    ])
    # Two matches with default limit=2 → ambiguous → returns None
    result = await resolve_node_id(g, target="foo", limit=2)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_kind_filter(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
        Node(
            id="function:src/a.py:Foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="Foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
        Node(
            id="class:src/a.py:Foo",
            kind=NodeKind.CLASS,
            source=NodeSource.CODE,
            name="Foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
    ])
    # Filter to CLASS kind → single match
    result = await resolve_node_id(g, target="Foo", kind=NodeKind.CLASS, limit=5)
    assert result == "class:src/a.py:Foo"
=======
from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.core.node import NodeKind
from loom.query.node_lookup import resolve_node_id, resolve_node_rows


@dataclass
class _FakeGraph:
    rows_by_query: list[tuple[str, list[dict[str, Any]]]] = field(default_factory=list)
    query_log: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.query_log.append((cypher, params))
        for marker, rows in self.rows_by_query:
            if marker in cypher:
                return rows
        return []


@pytest.mark.asyncio
async def test_resolve_node_rows_plain_name_uses_exact_name_lookup() -> None:
    graph = _FakeGraph(
        rows_by_query=[
            (
                "{name: $name}",
                [{"id": "function:src/x.py:f", "kind": "function", "path": "src/x.py"}],
            )
        ]
    )

    rows = await resolve_node_rows(graph, target="f", limit=2)

    assert len(rows) == 1
    assert "MATCH (n:Node {name: $name})" in graph.query_log[0][0]


@pytest.mark.asyncio
async def test_resolve_node_rows_qualified_name_prefers_exact_suffix_lookup() -> None:
    graph = _FakeGraph(
        rows_by_query=[
            (
                "n.id ENDS WITH $qualified_suffix",
                [
                    {
                        "id": "method:F:/loom/src/loom/core/graph.py:LoomGraph.neighbors",
                        "kind": "method",
                        "path": "F:/loom/src/loom/core/graph.py",
                    }
                ],
            )
        ]
    )

    rows = await resolve_node_rows(graph, target="LoomGraph.neighbors", limit=10)

    assert len(rows) == 1
    assert rows[0]["id"] == "method:F:/loom/src/loom/core/graph.py:LoomGraph.neighbors"
    assert len(graph.query_log) == 1


@pytest.mark.asyncio
async def test_resolve_node_rows_qualified_name_falls_back_to_leaf_lookup() -> None:
    graph = _FakeGraph(
        rows_by_query=[
            ("n.id ENDS WITH $qualified_suffix", []),
            (
                "n.name = $leaf_name",
                [{"id": "method:src/x.py:A.f", "kind": "method", "path": "src/x.py"}],
            ),
        ]
    )

    rows = await resolve_node_rows(graph, target="A.f", limit=10)

    assert len(rows) == 1
    assert len(graph.query_log) == 2


@pytest.mark.asyncio
async def test_resolve_node_id_returns_none_for_ambiguous_matches() -> None:
    graph = _FakeGraph(
        rows_by_query=[
            (
                "{name: $name}",
                [{"id": "function:src/a.py:f"}, {"id": "function:src/b.py:f"}],
            )
        ]
    )

    resolved = await resolve_node_id(graph, target="f", kind=NodeKind.FUNCTION, limit=2)

    assert resolved is None
>>>>>>> main
