from __future__ import annotations

from collections import defaultdict
from igraph import Graph

from ..edge import Edge, EdgeType
from ..node import Node
from . import cypher
from .edge_type_adapter import EdgeTypeAdapter
from .gateway import FalkorGateway
from .mappers import (
    deserialize_node_props,
    serialize_edge_props,
    serialize_node_props,
)


class NodeRepository:
    _CHUNK_SIZE = 500

    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def upsert(self, node: Node) -> None:
        props = serialize_node_props(node)
        label = node.kind.name.title()
        query = cypher.create_or_update_node_with_label(label)
        self._gw.run(query, params={"id": node.id, "props": props})

    def get(self, node_id: str) -> Node | None:
        rows = self._gw.query_rows(cypher.GET_NODE_BY_ID, params={"id": node_id})
        if not rows:
            return None
        props = deserialize_node_props(rows[0]["props"])
        return Node.model_validate(props)

    def delete(self, node_id: str) -> None:
        self._gw.run(cypher.DELETE_NODE_BY_ID, params={"id": node_id})

    def bulk_upsert(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        by_kind: dict[str, list[Node]] = defaultdict(list)
        for n in nodes:
            by_kind[n.kind.name.title()].append(n)

        for label, group in by_kind.items():
            payload = [{"id": n.id, "props": serialize_node_props(n)} for n in group]
            query = cypher.bulk_create_or_update_nodes_with_label(label)
            for i in range(0, len(payload), self._CHUNK_SIZE):
                chunk = payload[i : i + self._CHUNK_SIZE]
                self._gw.run(query, params={"nodes": chunk})


class EdgeRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def upsert(self, edge: Edge) -> None:
        rel_type = EdgeTypeAdapter.to_storage(edge.kind)
        query = cypher.create_or_update_edge(rel_type)
        props = serialize_edge_props(edge)
        self._gw.run(
            query,
            params={"from_id": edge.from_id, "to_id": edge.to_id, "props": props},
        )

    _CHUNK_SIZE = 500

    def bulk_upsert(self, edges: list[Edge]) -> None:
        if not edges:
            return

        by_kind: dict[EdgeType, list[Edge]] = defaultdict(list)
        for e in edges:
            by_kind[e.kind].append(e)

        for kind, group in by_kind.items():
            rel_type = EdgeTypeAdapter.to_storage(kind)
            query = cypher.bulk_create_or_update_edges(rel_type)
            payload = [
                {
                    "from_id": e.from_id,
                    "to_id": e.to_id,
                    "props": serialize_edge_props(e),
                }
                for e in group
            ]
            for i in range(0, len(payload), self._CHUNK_SIZE):
                chunk = payload[i : i + self._CHUNK_SIZE]
                self._gw.run(query, params={"edges": chunk})


class TraversalRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def neighbors(self, node_id: str, depth: int, edge_types: list[EdgeType]) -> list[Node]:
        if depth < 1:
            return []

        type_names = EdgeTypeAdapter.to_storage_list(edge_types)

        frontier: set[str] = {node_id}
        visited: set[str] = {node_id}
        results: dict[str, Node] = {}
        graph_nodes: set[str] = {node_id}
        graph_edges: list[tuple[str, str]] = []

        for _ in range(depth):
            if not frontier:
                break

            rows = self._gw.query_rows(
                cypher.NEIGHBORS_STEP_WITH_SOURCE,
                params={"ids": list(frontier), "types": type_names},
            )

            next_frontier: set[str] = set()
            for row in rows:
                from_id = row.get("from_id")
                to_id = row.get("to_id")
                props = deserialize_node_props(row["props"])
                node = Node.model_validate(props)
                if isinstance(from_id, str) and isinstance(to_id, str):
                    graph_nodes.add(from_id)
                    graph_nodes.add(to_id)
                    graph_edges.append((from_id, to_id))
                if node.id not in visited:
                    visited.add(node.id)
                    next_frontier.add(node.id)
                results[node.id] = node

            frontier = next_frontier

        if not results:
            return []

        ordered_ids = self._rank_by_personalized_pagerank(node_id, graph_nodes, graph_edges)
        ranked_nodes = [results[node_id] for node_id in ordered_ids if node_id in results]
        remaining = [node for node_id, node in results.items() if node_id not in set(ordered_ids)]
        return ranked_nodes + remaining

    @staticmethod
    def _rank_by_personalized_pagerank(
        seed_id: str,
        node_ids: set[str],
        edges: list[tuple[str, str]],
    ) -> list[str]:
        ordered_node_ids = sorted(node_ids)
        index_by_id = {node_id: index for index, node_id in enumerate(ordered_node_ids)}
        graph = Graph(directed=True)
        graph.add_vertices(len(ordered_node_ids))
        if edges:
            graph.add_edges([(index_by_id[source], index_by_id[target]) for source, target in edges])

        reset = [0.0] * len(ordered_node_ids)
        reset[index_by_id[seed_id]] = 1.0
        scores = graph.personalized_pagerank(directed=True, reset=reset)

        ranked = sorted(
            ((node_id, scores[index_by_id[node_id]]) for node_id in ordered_node_ids if node_id != seed_id),
            key=lambda item: item[1],
            reverse=True,
        )
        return [node_id for node_id, _ in ranked]
