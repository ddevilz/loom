from __future__ import annotations

from collections import defaultdict

from ..edge import Edge, EdgeType
from ..node import Node
from . import queries
from .gateway import FalkorGateway
from .mappers import (
    deserialize_node_props,
    serialize_edge_props,
    serialize_node_props,
)


class NodeRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def upsert(self, node: Node) -> None:
        props = serialize_node_props(node)
        self._gw.run(queries.CREATE_OR_UPDATE_NODE, params={"id": node.id, "props": props})

    def get(self, node_id: str) -> Node | None:
        rows = self._gw.query_rows(queries.GET_NODE_BY_ID, params={"id": node_id})
        if not rows:
            return None
        props = deserialize_node_props(rows[0]["props"])
        return Node.model_validate(props)

    def delete(self, node_id: str) -> None:
        self._gw.run(queries.DELETE_NODE_BY_ID, params={"id": node_id})

    def bulk_upsert(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        payload = [{"id": n.id, "props": serialize_node_props(n)} for n in nodes]
        self._gw.run(queries.BULK_CREATE_OR_UPDATE_NODES, params={"nodes": payload})


class EdgeRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def upsert(self, edge: Edge) -> None:
        rel_type = edge.kind.name
        cypher = queries.create_or_update_edge(rel_type)
        props = serialize_edge_props(edge)
        self._gw.run(
            cypher,
            params={"from_id": edge.from_id, "to_id": edge.to_id, "props": props},
        )

    def bulk_upsert(self, edges: list[Edge]) -> None:
        if not edges:
            return

        by_kind: dict[EdgeType, list[Edge]] = defaultdict(list)
        for e in edges:
            by_kind[e.kind].append(e)

        for kind, group in by_kind.items():
            rel_type = kind.name
            cypher = queries.bulk_create_or_update_edges(rel_type)
            payload = [
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "props": serialize_edge_props(e),
                }
                for e in group
            ]
            self._gw.run(cypher, params={"edges": payload})


class TraversalRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def neighbors(self, node_id: str, depth: int, edge_types: list[EdgeType]) -> list[Node]:
        if depth < 1:
            return []

        type_names = [t.name for t in edge_types]

        frontier: set[str] = {node_id}
        visited: set[str] = {node_id}
        results: dict[str, Node] = {}

        for _ in range(depth):
            if not frontier:
                break

            rows = self._gw.query_rows(
                queries.NEIGHBORS_STEP,
                params={"ids": list(frontier), "types": type_names},
            )

            next_frontier: set[str] = set()
            for row in rows:
                props = deserialize_node_props(row["props"])
                node = Node.model_validate(props)
                if node.id not in visited:
                    visited.add(node.id)
                    next_frontier.add(node.id)
                results[node.id] = node

            frontier = next_frontier

        return list(results.values())
