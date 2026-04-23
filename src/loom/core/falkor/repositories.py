from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter

from ..edge import Edge, EdgeType
from ..node import Node, NodeKind, NodeSource
from . import cypher
from .edge_type_adapter import EdgeTypeAdapter
from .gateway import FalkorGateway
from .mappers import (
    deserialize_metadata_value,
    deserialize_node_props,
    row_to_node,
    serialize_edge_props,
    serialize_node_props,
)

logger = logging.getLogger(__name__)


def _rank_by_personalized_pagerank(
    seed_id: str,
    node_ids: set[str],
    edges: list[tuple[str, str]],
) -> list[str]:
    from igraph import Graph

    ordered_node_ids = sorted(node_ids)
    index_by_id = {node_id: index for index, node_id in enumerate(ordered_node_ids)}
    graph = Graph(directed=True)
    graph.add_vertices(len(ordered_node_ids))
    if edges:
        graph.add_edges(
            [(index_by_id[source], index_by_id[target]) for source, target in edges]
        )

    reset = [0.0] * len(ordered_node_ids)
    reset[index_by_id[seed_id]] = 1.0
    scores = graph.personalized_pagerank(directed=True, reset=reset)

    ranked = sorted(
        (
            (node_id, scores[index_by_id[node_id]])
            for node_id in ordered_node_ids
            if node_id != seed_id
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    return [node_id for node_id, _ in ranked]


class NodeRepository:
    _CHUNK_SIZE = 1000

    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    @staticmethod
    def _split_embedding(
        props: dict[str, object],
    ) -> tuple[dict[str, object], list[float] | None]:
        raw = props.get("embedding")
        if isinstance(raw, list):
            embedding = [float(x) for x in raw if isinstance(x, (int, float))]
            props = dict(props)
            props.pop("embedding", None)
            return props, (embedding or None)
        return props, None

    def upsert(self, node: Node) -> None:
        props, embedding = self._split_embedding(serialize_node_props(node))
        label = node.kind.name.title()
        query = cypher.create_or_update_node_with_label(label)
        self._gw.run(
            query, params={"id": node.id, "props": props, "embedding": embedding}
        )

    def get(self, node_id: str) -> Node | None:
        rows = self._gw.query_rows(cypher.GET_NODE_BY_ID, params={"id": node_id})
        if not rows:
            return None
        props = rows[0].get("props")
        if not isinstance(props, dict):
            return None
        props = deserialize_node_props(props)
        source_raw = props.get("source")
        source = (
            NodeSource._value2member_map_.get(source_raw)
            if isinstance(source_raw, str)
            else None
        )
        if source is None:
            source = (
                NodeSource.DOC
                if str(props.get("id", "")).startswith("doc:")
                else NodeSource.CODE
            )
        fallback_kind = (
            NodeKind.SECTION if source == NodeSource.DOC else NodeKind.FUNCTION
        )
        node = row_to_node(
            {
                "id": props.get("id"),
                "kind": props.get("kind"),
                "name": props.get("name"),
                "summary": props.get("summary"),
                "path": props.get("path"),
                "metadata": deserialize_metadata_value(props.get("metadata")),
                "embedding": props.get("embedding"),
            },
            source=source,
            fallback_kind=fallback_kind,
            allow_embedding=True,
            require_str_id=True,
            require_valid_kind=True,
        )
        if node is None:
            return None
        community_id = props.get("community_id")
        return node.model_copy(
            update={
                "community_id": community_id if isinstance(community_id, str) else None
            }
        )

    def delete(self, node_id: str) -> None:
        self._gw.run(cypher.DELETE_NODE_BY_ID, params={"id": node_id})

    def bulk_upsert(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        by_kind: dict[str, list[Node]] = defaultdict(list)
        for n in nodes:
            by_kind[n.kind.name.title()].append(n)

        for label, group in by_kind.items():
            payload = []
            for n in group:
                props, embedding = self._split_embedding(serialize_node_props(n))
                payload.append({"id": n.id, "props": props, "embedding": embedding})
            query = cypher.bulk_create_or_update_nodes_with_label(label)
            chunk_count = (len(payload) + self._CHUNK_SIZE - 1) // self._CHUNK_SIZE
            t0 = perf_counter()
            for i in range(0, len(payload), self._CHUNK_SIZE):
                chunk = payload[i : i + self._CHUNK_SIZE]
                self._gw.run(query, params={"nodes": chunk})
            logger.info(
                "falkor bulk_upsert_nodes label=%s count=%d chunk_size=%d chunks=%d duration_ms=%.2f",
                label,
                len(payload),
                self._CHUNK_SIZE,
                chunk_count,
                (perf_counter() - t0) * 1000.0,
            )


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

    _CHUNK_SIZE = 1000

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
            chunk_count = (len(payload) + self._CHUNK_SIZE - 1) // self._CHUNK_SIZE
            t0 = perf_counter()
            for i in range(0, len(payload), self._CHUNK_SIZE):
                chunk = payload[i : i + self._CHUNK_SIZE]
                self._gw.run(query, params={"edges": chunk})
            logger.info(
                "falkor bulk_upsert_edges rel_type=%s count=%d chunk_size=%d chunks=%d duration_ms=%.2f",
                rel_type,
                len(payload),
                self._CHUNK_SIZE,
                chunk_count,
                (perf_counter() - t0) * 1000.0,
            )


class TraversalRepository:
    def __init__(self, gw: FalkorGateway) -> None:
        self._gw = gw

    def _traverse_ranked(
        self,
        *,
        seed_id: str,
        depth: int,
        query: str,
        params: dict[str, object],
        source_key: str,
        target_key: str,
    ) -> list[Node]:
        if depth < 1:
            return []

        frontier: set[str] = {seed_id}
        visited: set[str] = {seed_id}
        results: dict[str, Node] = {}
        graph_nodes: set[str] = {seed_id}
        graph_edges: list[tuple[str, str]] = []
        depth_by_id: dict[str, int] = {seed_id: 0}
        parent_by_id: dict[str, str] = {}

        for current_depth in range(1, depth + 1):
            if not frontier:
                break

            rows = self._gw.query_rows(
                query,
                params={**params, "ids": list(frontier)},
            )

            next_frontier: set[str] = set()
            for row in rows:
                source_id = row.get(source_key)
                target_id = row.get(target_key)
                props = row.get("props")
                if not isinstance(props, dict):
                    continue
                node = Node.model_validate(deserialize_node_props(props))
                if isinstance(source_id, str) and isinstance(target_id, str):
                    graph_nodes.add(source_id)
                    graph_nodes.add(target_id)
                    graph_edges.append((source_id, target_id))
                if node.id not in visited:
                    visited.add(node.id)
                    next_frontier.add(node.id)
                    depth_by_id[node.id] = current_depth
                    if isinstance(target_id, str):
                        parent_by_id[node.id] = target_id
                node.depth = depth_by_id.get(node.id)
                node.parent_id = parent_by_id.get(node.id)
                results[node.id] = node

            frontier = next_frontier

        if not results:
            return []

        ordered_ids = _rank_by_personalized_pagerank(seed_id, graph_nodes, graph_edges)
        ordered_id_set = set(ordered_ids)
        ranked = [results[node_id] for node_id in ordered_ids if node_id in results]
        remaining = [
            node for node_id, node in results.items() if node_id not in ordered_id_set
        ]
        return ranked + remaining

    def neighbors(
        self, node_id: str, depth: int, edge_types: list[EdgeType]
    ) -> list[Node]:
        type_names = EdgeTypeAdapter.to_storage_list(edge_types)
        return self._traverse_ranked(
            seed_id=node_id,
            depth=depth,
            query=cypher.NEIGHBORS_STEP_WITH_SOURCE,
            params={"types": type_names},
            source_key="from_id",
            target_key="to_id",
        )

    def blast_radius(self, node_id: str, depth: int) -> list[Node]:
        """BFS over incoming CALLS edges to find all nodes affected if node_id changes.

        Direction: caller → callee.  We walk *backwards* (who calls us, then who
        calls them, etc.) so the result is the set of nodes that would break if
        this node's contract changes.  PPR runs only on the CALLS subgraph so
        CONTAINS edges don't pollute the ranking.
        """
        return self._traverse_ranked(
            seed_id=node_id,
            depth=depth,
            query=cypher.BLAST_RADIUS_STEP,
            params={},
            source_key="from_id",
            target_key="to_id",
        )
