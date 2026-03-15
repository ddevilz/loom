from __future__ import annotations

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
