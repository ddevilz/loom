from __future__ import annotations

import asyncio
from typing import Any, Protocol

from loom.config import LOOM_EMBED_DIM
from loom.query.node_lookup import resolve_node_id

from .edge import Edge, EdgeType
from .falkor.gateway import FalkorGateway
from .falkor.repositories import EdgeRepository, NodeRepository, TraversalRepository
from .falkor.schema import invalidate_schema_init, schema_init
from .node import Node, NodeKind


class _Gateway(Protocol):
    graph_name: str

    def reconnect(self) -> None: ...

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ): ...

    def query_rows(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]: ...


class LoomGraph:
    def __init__(
        self, graph_name: str = "loom", *, gateway: _Gateway | None = None
    ) -> None:
        self.graph_name = graph_name
        self._gw: _Gateway = gateway or FalkorGateway(graph_name=graph_name)
        self._nodes = NodeRepository(self._gw)
        self._edges = EdgeRepository(self._gw)
        self._traversal = TraversalRepository(self._gw)
        self._schema_lock: asyncio.Lock | None = None
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        if self._schema_lock is None:
            self._schema_lock = asyncio.Lock()
        async with self._schema_lock:
            if self._schema_ready:
                return
            await asyncio.to_thread(schema_init, self._gw, embedding_dim=LOOM_EMBED_DIM)
            self._schema_ready = True

    async def schema_init(self) -> None:
        await self._ensure_schema()

    async def delete(self) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._gw.run, "MATCH (n) DETACH DELETE n")

    def reconnect(self) -> None:
        self._gw.reconnect()
        invalidate_schema_init(self.graph_name)
        self._schema_ready = False

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        await self._ensure_schema()
        return await asyncio.to_thread(self._gw.query_rows, cypher, params)

    async def create_node(self, node: Node) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._nodes.upsert, node)

    async def get_node(self, node_id: str) -> Node | None:
        await self._ensure_schema()
        return await asyncio.to_thread(self._nodes.get, node_id)

    async def delete_node(self, node_id: str) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._nodes.delete, node_id)

    async def create_edge(self, edge: Edge) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._edges.upsert, edge)

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._nodes.bulk_upsert, nodes)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._edges.bulk_upsert, edges)

    async def blast_radius(
        self,
        node_id: str,
        depth: int = 3,
    ) -> list[Node]:
        """Return nodes that would be affected (callers, transitively) if node_id changes.

        Uses incoming CALLS BFS with PPR ranking on the CALLS-only subgraph.
        This is the correct direction for blast radius: who breaks if I change this?
        """
        await self._ensure_schema()
        return await asyncio.to_thread(
            self._traversal.blast_radius,
            node_id=node_id,
            depth=depth,
        )

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind: NodeKind | None = None,
    ) -> list[Node]:
        await self._ensure_schema()
        resolved_node_id = node_id
        if ":" not in node_id:
            resolved = await resolve_node_id(
                self,
                target=node_id,
                kind=kind,
                limit=2,
            )
            if resolved is None:
                return []
            resolved_node_id = resolved
        types = list(EdgeType) if edge_types is None else edge_types
        return await asyncio.to_thread(
            self._traversal.neighbors,
            node_id=resolved_node_id,
            depth=depth,
            edge_types=types,
        )
