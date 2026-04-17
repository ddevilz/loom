from __future__ import annotations

from typing import Any, Protocol

from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind


class QueryGraph(Protocol):
    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


class BulkGraph(QueryGraph, Protocol):
    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...
    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


class EdgeWriteGraph(Protocol):
    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


class NeighborGraph(QueryGraph, Protocol):
    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind: NodeKind | None = None,
    ) -> list[Node]: ...
