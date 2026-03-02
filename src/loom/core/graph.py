from __future__ import annotations

from typing import Any

from .edge import Edge, EdgeType
from .node import Node

from .falkor.gateway import FalkorGateway
from .falkor.repositories import EdgeRepository, NodeRepository, TraversalRepository


class LoomGraph:
    def __init__(self, graph_name: str = "loom") -> None:
        self.graph_name = graph_name
        self._gw = FalkorGateway(graph_name=graph_name)
        self.nodes = NodeRepository(self._gw)
        self.edges = EdgeRepository(self._gw)
        self.traversal = TraversalRepository(self._gw)

    def reconnect(self) -> None:
        self._gw.reconnect()

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._gw.query_rows(cypher, params=params)

    def create_node(self, node: Node) -> None:
        self.nodes.upsert(node)

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def delete_node(self, node_id: str) -> None:
        self.nodes.delete(node_id)

    def create_edge(self, edge: Edge) -> None:
        self.edges.upsert(edge)

    def bulk_create_nodes(self, nodes: list[Node]) -> None:
        self.nodes.bulk_upsert(nodes)

    def bulk_create_edges(self, edges: list[Edge]) -> None:
        self.edges.bulk_upsert(edges)

    def neighbors(self, node_id: str, depth: int = 1, edge_types: list[EdgeType] | None = None) -> list[Node]:
        types = edge_types or list(EdgeType)
        return self.traversal.neighbors(node_id=node_id, depth=depth, edge_types=types)
