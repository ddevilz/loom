from __future__ import annotations

from loom.core.node import NodeKind

GET_NODE_BY_ID = "MATCH (n:Node {id: $id}) RETURN properties(n) AS props LIMIT 1"
DELETE_NODE_BY_ID = "MATCH (n:Node {id: $id}) DETACH DELETE n"
COUNT_NODES = "MATCH (n) RETURN count(n) AS c"
CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"

CREATE_OR_UPDATE_NODE = "MERGE (n:Node {id: $id}) SET n += $props RETURN n"

BULK_CREATE_OR_UPDATE_NODES = (
    "UNWIND $nodes AS n MERGE (node:Node {id: n.id}) SET node += n.props"
)

NEIGHBORS_STEP = (
    "UNWIND $ids AS id "
    "MATCH (n:Node {id: id})-[r]->(m:Node) "
    "WHERE type(r) IN $types "
    "RETURN DISTINCT properties(m) AS props"
)

NEIGHBORS_STEP_WITH_SOURCE = (
    "UNWIND $ids AS id "
    "MATCH (n:Node {id: id})-[r]->(m:Node) "
    "WHERE type(r) IN $types "
    "RETURN DISTINCT n.id AS from_id, m.id AS to_id, properties(m) AS props"
)


def create_or_update_edge(rel_type: str) -> str:
    return (
        "MATCH (a:Node {id: $from_id}), (b:Node {id: $to_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += $props "
        "RETURN r"
    )


def create_or_update_node_with_label(label: str) -> str:
    stale_labels = [
        kind.name.title() for kind in NodeKind if kind.name.title() != label
    ]
    remove_clause = " ".join(
        f"REMOVE n:`{stale_label}`" for stale_label in stale_labels
    )
    return (
        "MERGE (n:Node {id: $id}) "
        "SET n += $props "
        "FOREACH (_ IN CASE WHEN $embedding IS NULL THEN [] ELSE [1] END | SET n.embedding = vecf32($embedding)) "
        f"{remove_clause} "
        f"SET n:`{label}` "
        "RETURN n"
    )


def bulk_create_or_update_nodes_with_label(label: str) -> str:
    stale_labels = [
        kind.name.title() for kind in NodeKind if kind.name.title() != label
    ]
    remove_clause = " ".join(
        f"REMOVE node:`{stale_label}`" for stale_label in stale_labels
    )
    return (
        "UNWIND $nodes AS n "
        "MERGE (node:Node {id: n.id}) "
        "SET node += n.props "
        "FOREACH (_ IN CASE WHEN n.embedding IS NULL THEN [] ELSE [1] END | SET node.embedding = vecf32(n.embedding)) "
        f"{remove_clause} "
        f"SET node:`{label}`"
    )


def bulk_create_or_update_edges(rel_type: str) -> str:
    return (
        "UNWIND $edges AS e "
        "MATCH (a:Node {id: e.from_id}), (b:Node {id: e.to_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += e.props"
    )
