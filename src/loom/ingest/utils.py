from __future__ import annotations

from typing import Any, Protocol

from loom.core import Node, NodeSource
from loom.core.falkor.mappers import deserialize_node_props


_DELETE_NON_HUMAN_OUTGOING_EDGES_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin IS NULL OR r.origin <> 'human'
DELETE r
"""

_DELETE_NON_HUMAN_INCOMING_EDGES_FOR_FILE = """
MATCH ()-[r]->(a {path: $path})
WHERE r.origin IS NULL OR r.origin <> 'human'
DELETE r
"""

_MARK_HUMAN_OUTGOING_EDGES_STALE_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = 'source_changed'
"""

_MARK_HUMAN_INCOMING_EDGES_STALE_FOR_FILE = """
MATCH ()-[r]->(a {path: $path})
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = 'source_changed'
"""


class EdgeInvalidationGraph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


async def invalidate_edges_for_file(graph: EdgeInvalidationGraph, *, path: str) -> None:
    await graph.query(_DELETE_NON_HUMAN_OUTGOING_EDGES_FOR_FILE, {"path": path})
    await graph.query(_DELETE_NON_HUMAN_INCOMING_EDGES_FOR_FILE, {"path": path})
    await graph.query(_MARK_HUMAN_OUTGOING_EDGES_STALE_FOR_FILE, {"path": path})
    await graph.query(_MARK_HUMAN_INCOMING_EDGES_STALE_FOR_FILE, {"path": path})


async def get_doc_nodes_for_linking(graph: EdgeInvalidationGraph) -> list[Node]:
    rows = await graph.query("MATCH (n) WHERE n.id STARTS WITH 'doc:' RETURN properties(n) AS props")
    out: list[Node] = []
    for row in rows:
        props = row.get("props")
        if not isinstance(props, dict):
            continue
        props = deserialize_node_props(props)
        try:
            node = Node.model_validate(props)
        except Exception:
            continue
        if node.source == NodeSource.DOC:
            out.append(node)
    return out


def merge_nodes_by_id(*node_lists: list[Node]) -> list[Node]:
    merged: dict[str, Node] = {}
    for nodes in node_lists:
        for node in nodes:
            merged[node.id] = node
    return list(merged.values())


async def get_node_ids_by_path(graph: EdgeInvalidationGraph, *, path: str) -> list[str]:
    rows = await graph.query("MATCH (n {path: $path}) RETURN n.id AS id", {"path": path})
    return [row.get("id") for row in rows if isinstance(row.get("id"), str)]


async def node_has_human_edges(graph: EdgeInvalidationGraph, *, node_id: str) -> bool:
    outgoing_rows = await graph.query(
        """
MATCH (n {id: $id})-[r]->()
WHERE r.origin = 'human'
RETURN count(r) AS c
""",
        {"id": node_id},
    )
    incoming_rows = await graph.query(
        """
MATCH ()-[r]->(n {id: $id})
WHERE r.origin = 'human'
RETURN count(r) AS c
""",
        {"id": node_id},
    )
    return (bool(outgoing_rows) and int(outgoing_rows[0].get("c", 0)) > 0) or (
        bool(incoming_rows) and int(incoming_rows[0].get("c", 0)) > 0
    )


async def mark_human_edges_stale_for_node(
    graph: EdgeInvalidationGraph,
    *,
    node_id: str,
    reason: str,
) -> None:
    await graph.query(
        """
MATCH (n {id: $id})-[r]->()
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = $reason
""",
        {"id": node_id, "reason": reason},
    )
    await graph.query(
        """
MATCH ()-[r]->(n {id: $id})
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = $reason
""",
        {"id": node_id, "reason": reason},
    )


async def delete_nodes_by_ids(graph: EdgeInvalidationGraph, ids: list[str]) -> None:
    if not ids:
        return
    await graph.query(
        "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n",
        {"ids": ids},
    )


async def delete_nodes_by_path(graph: EdgeInvalidationGraph, *, path: str) -> None:
    await graph.query("MATCH (n {path: $path}) DETACH DELETE n", {"path": path})
