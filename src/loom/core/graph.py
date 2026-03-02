from __future__ import annotations

import asyncio
from typing import Any

from .edge import Edge, EdgeType
from .node import Node

from .falkor.gateway import FalkorGateway
from .falkor.repositories import EdgeRepository, NodeRepository, TraversalRepository
from .falkor.schema import schema_init


class LoomGraph:
    def __init__(self, graph_name: str = "loom") -> None:
        self.graph_name = graph_name
        self._gw = FalkorGateway(graph_name=graph_name)
        schema_init(self._gw)
        self.nodes = NodeRepository(self._gw)
        self.edges = EdgeRepository(self._gw)
        self.traversal = TraversalRepository(self._gw)

    async def schema_init(self) -> None:
        await asyncio.to_thread(schema_init, self._gw)

    def reconnect(self) -> None:
        self._gw.reconnect()

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._gw.query_rows, cypher, params)

    async def create_node(self, node: Node) -> None:
        await asyncio.to_thread(self.nodes.upsert, node)

    async def get_node(self, node_id: str) -> Node | None:
        return await asyncio.to_thread(self.nodes.get, node_id)

    async def delete_node(self, node_id: str) -> None:
        await asyncio.to_thread(self.nodes.delete, node_id)

    async def create_edge(self, edge: Edge) -> None:
        await asyncio.to_thread(self.edges.upsert, edge)

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        await asyncio.to_thread(self.nodes.bulk_upsert, nodes)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        await asyncio.to_thread(self.edges.bulk_upsert, edges)

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        resolved_id = node_id
        if ":" not in node_id:
            rows = await self.query(
                "MATCH (f:Function {name: $name}) RETURN f.id AS id LIMIT 1",
                params={"name": node_id},
            )
            if not rows:
                return []
            resolved_id = rows[0]["id"]

        types = edge_types or list(EdgeType)
        return await asyncio.to_thread(
            self.traversal.neighbors,
            node_id=resolved_id,
            depth=depth,
            edge_types=types,
        )
