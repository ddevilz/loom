from __future__ import annotations

# Keeping Cypher in one place for readability. (For now!)

GET_NODE_BY_ID = "MATCH (n:Node {id: $id}) RETURN properties(n) AS props LIMIT 1"
DELETE_NODE_BY_ID = "MATCH (n:Node {id: $id}) DETACH DELETE n"
COUNT_NODES = "MATCH (n) RETURN count(n) AS c"
CLEAR_GRAPH = "MATCH (n) DETACH DELETE n"

CREATE_OR_UPDATE_NODE = "MERGE (n:Node {id: $id}) SET n += $props RETURN n"

BULK_CREATE_OR_UPDATE_NODES = (
    "UNWIND $nodes AS n "
    "MERGE (node:Node {id: n.id}) "
    "SET node += n.props"
)

NEIGHBORS_STEP = (
    "UNWIND $ids AS id "
    "MATCH (n:Node {id: id})-[r]->(m:Node) "
    "WHERE type(r) IN $types "
    "RETURN DISTINCT properties(m) AS props"
)


def create_or_update_edge(rel_type: str) -> str:
    return (
        "MATCH (a:Node {id: $from_id}), (b:Node {id: $to_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += $props "
        "RETURN r"
    )


def bulk_create_or_update_edges(rel_type: str) -> str:
    return (
        "UNWIND $edges AS e "
        "MATCH (a:Node {id: e.from_id}), (b:Node {id: e.to_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += e.props"
    )
