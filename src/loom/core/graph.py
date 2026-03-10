from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from loom.config import LOOM_EMBED_DIM
from loom.errors import BulkSizeLimitError

from .edge_model import Edge, EdgeType
from .falkor.gateway import FalkorGateway
from .falkor.repositories import EdgeRepository, NodeRepository, TraversalRepository
from .falkor.schema import invalidate_schema_init, schema_init
from .gateway import _Gateway
from .node_model import Node
from .schema_locks import _get_schema_lock
from .validation import validate_full_node_id

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BULK_SIZE_LIMIT = 10_000  # hard cap for bulk operations

_T = TypeVar("_T")


class LoomGraph:
    def __init__(
        self,
        graph_name: str = "loom",
        *,
        gateway: _Gateway | None = None,
    ) -> None:
        self.graph_name = graph_name
        self._gw: _Gateway = gateway or FalkorGateway(graph_name=graph_name)
        self._nodes = NodeRepository(self._gw)
        self._edges = EdgeRepository(self._gw)
        self._traversal = TraversalRepository(self._gw)

        # Memoisation flag — set once, cleared only on reconnect.
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        """Initialise schema exactly once per instance (thread-safe)."""
        if self._schema_ready:
            return

        lock = await _get_schema_lock(self.graph_name)
        async with lock:
            # Re-check after acquiring the lock (another coroutine may have
            # finished init while we were waiting).
            if self._schema_ready:
                return

            log.debug("Initialising schema for graph '%s'", self.graph_name)
            await asyncio.to_thread(schema_init, self._gw, embedding_dim=LOOM_EMBED_DIM)
            self._schema_ready = True
            log.debug("Schema ready for graph '%s'", self.graph_name)

    async def _run(self, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        """Ensure schema is ready, then execute *fn* in a thread."""
        await self._ensure_schema()
        return await asyncio.to_thread(fn, *args, **kwargs)

    def reconnect(self) -> None:
        """Re-establish the gateway connection and reset schema state."""
        log.info("Reconnecting gateway for graph '%s'", self.graph_name)
        self._gw.reconnect()
        invalidate_schema_init(self.graph_name)
        self._schema_ready = False

    async def query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute an arbitrary Cypher query and return rows."""
        return await self._run(self._gw.query_rows, cypher, params)

    async def create_node(self, node: Node) -> None:
        await self._run(self._nodes.upsert, node)

    async def get_node(self, node_id: str) -> Node | None:
        return await self._run(self._nodes.get, node_id)

    async def delete_node(self, node_id: str) -> None:
        await self._run(self._nodes.delete, node_id)

    async def create_edge(self, edge: Edge) -> None:
        await self._run(self._edges.upsert, edge)

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        if len(nodes) > _BULK_SIZE_LIMIT:
            raise BulkSizeLimitError(
                f"bulk_create_nodes received {len(nodes):,} items; "
                f"limit is {_BULK_SIZE_LIMIT:,}. "
                "Batch your input and call in chunks."
            )
        await self._run(self._nodes.bulk_upsert, nodes)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        if len(edges) > _BULK_SIZE_LIMIT:
            raise BulkSizeLimitError(
                f"bulk_create_edges received {len(edges):,} items; "
                f"limit is {_BULK_SIZE_LIMIT:,}. "
                "Batch your input and call in chunks."
            )
        await self._run(self._edges.bulk_upsert, edges)

    async def delete_all(self, *, confirm: bool = False) -> None:
        """Delete **every** node and edge in the graph.

        Parameters
        ----------
        confirm:
            Must be ``True`` to execute.  Forces callers to be intentional.
        """
        if not confirm:
            raise ValueError(
                "Refusing to delete all graph data without explicit confirmation. "
                "Pass confirm=True to proceed."
            )
        log.warning("Deleting all data in graph '%s'", self.graph_name)
        await self._run(self._gw.run, "MATCH (n) DETACH DELETE n")

    async def blast_radius(
        self,
        node_id: str,
        depth: int = 3,
    ) -> list[Node]:
        """Return nodes that would be affected if node_id changes.

        Args:
            node_id: Full node ID (e.g., "function:auth.py:validate")
            depth: BFS depth limit

        Returns:
            List of nodes that depend on this node
        """
        # Validate it's a full ID
        validate_full_node_id(node_id, "blast_radius")

        log.debug("blast_radius: node=%s depth=%d", node_id, depth)
        return await self._run(
            self._traversal.blast_radius,
            node_id=node_id,
            depth=depth,
        )

    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Node]:
        """Return nodes reachable from node_id within depth hops.

        Args:
            node_id: Full node ID (e.g., "function:auth.py:validate")
            depth: Traversal depth limit
            edge_types: Edge types to follow (defaults to all)

        Returns:
            List of neighboring nodes
        """
        # Validate that node_id is a full ID
        validate_full_node_id(node_id, "neighbors")

        types = list(EdgeType) if edge_types is None else edge_types
        return await self._run(
            self._traversal.neighbors,
            node_id=node_id,
            depth=depth,
            edge_types=types,
        )
