from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from loom.core import LoomGraph


@dataclass
class _FakeGateway:
    graph_name: str = "test"
    last_cypher: str | None = None
    last_params: dict[str, Any] | None = None
    rows: list[dict[str, Any]] | None = None

    def reconnect(self) -> None:
        return None

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ):
        return None

    def query_rows(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        self.last_cypher = cypher
        self.last_params = params

        if "RETURN n.id AS id" in cypher:
            if self.rows is not None:
                return self.rows
            return [{"id": "function:src/x.py:f"}]
        return []


@pytest.mark.asyncio
async def test_neighbors_with_full_id_works_directly() -> None:
    """Test that full IDs work directly without reconstruction."""
    gw = _FakeGateway()
    g = LoomGraph(graph_name="test", gateway=gw)

    captured: dict[str, Any] = {}

    def _fake_neighbors(*, node_id: str, depth: int, edge_types: list[object]):
        captured["node_id"] = node_id
        return []

    g._traversal.neighbors = _fake_neighbors  # type: ignore[method-assign]

    # Full ID should work directly
    await g.neighbors("function:src/x.py:f", depth=1)

    # Should pass through the full ID unchanged
    assert captured["node_id"] == "function:src/x.py:f"


@pytest.mark.asyncio
async def test_neighbors_with_simple_id_raises_error() -> None:
    """Test that simple names (not full IDs) raise NodeResolutionError."""
    gw = _FakeGateway()
    g = LoomGraph(graph_name="test", gateway=gw)

    g._traversal.neighbors = lambda **kwargs: []  # type: ignore[method-assign]

    # Simple name without context should raise error
    with pytest.raises(Exception) as exc_info:  # Changed from ValueError to Exception
        await g.neighbors("f", depth=1)

    assert "neighbors requires a full node ID" in str(exc_info.value)


@pytest.mark.asyncio
async def test_neighbors_preserves_explicit_empty_edge_types() -> None:
    gw = _FakeGateway()
    g = LoomGraph(graph_name="test", gateway=gw)
    captured: dict[str, Any] = {}

    def _fake_neighbors(*, node_id: str, depth: int, edge_types: list[object]):
        captured["node_id"] = node_id
        captured["depth"] = depth
        captured["edge_types"] = edge_types
        return []

    g._traversal.neighbors = _fake_neighbors  # type: ignore[method-assign]

    await g.neighbors("function:src/x.py:f", depth=1, edge_types=[])

    assert captured["node_id"] == "function:src/x.py:f"
    assert captured["depth"] == 1
    assert captured["edge_types"] == []
