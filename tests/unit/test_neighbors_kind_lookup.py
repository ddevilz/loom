from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from loom.core import LoomGraph, NodeKind


@dataclass
class _FakeGateway:
    graph_name: str = "test"
    last_cypher: str | None = None
    last_params: dict[str, Any] | None = None

    def reconnect(self) -> None:
        return None

    def run(self, cypher: str, params: dict[str, Any] | None = None, *, timeout: int | None = None):
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
            return [{"id": "function:src/x.py:f"}]
        return []


@pytest.mark.asyncio
async def test_neighbors_resolves_plain_name_without_kind_uses_node_label() -> None:
    gw = _FakeGateway()
    g = LoomGraph(graph_name="test", gateway=gw)

    # Avoid hitting traversal layer.
    g._traversal.neighbors = lambda **kwargs: []  # type: ignore[method-assign]

    await g.neighbors("f", depth=1)
    assert gw.last_cypher is not None
    assert "MATCH (n:Node {name: $name})" in gw.last_cypher


@pytest.mark.asyncio
async def test_neighbors_resolves_plain_name_with_kind_uses_kind_label() -> None:
    gw = _FakeGateway()
    g = LoomGraph(graph_name="test", gateway=gw)

    g._traversal.neighbors = lambda **kwargs: []  # type: ignore[method-assign]

    await g.neighbors("f", depth=1, kind=NodeKind.FUNCTION)
    assert gw.last_cypher is not None
    assert "MATCH (n:`Function` {name: $name})" in gw.last_cypher
