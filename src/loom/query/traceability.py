from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from loom.core import Node, NodeKind, NodeSource, EdgeType
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter


_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class TraceCoverageReport:
    sprint_name: str
    ticket_count: int
    linked_function_count: int


def _row_to_doc_node(row: dict[str, Any]) -> Node:
    return Node(
        id=str(row.get("id")),
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=str(row.get("name")),
        summary=row.get("summary"),
        path=str(row.get("path")),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


def _row_to_code_node(row: dict[str, Any]) -> Node:
    kind = NodeKind(str(row.get("kind") or NodeKind.FUNCTION.value))
    return Node(
        id=str(row.get("id")),
        kind=kind,
        source=NodeSource.CODE,
        name=str(row.get("name")),
        summary=row.get("summary"),
        path=str(row.get("path")),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


async def unimplemented_tickets(graph: _Graph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (t {{source: 'doc'}}) WHERE t.path STARTS WITH 'jira://' AND NOT ( ()-[:{_LOOM_IMPL_REL}]->(t) ) RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata"
    )
    return [_row_to_doc_node(row) for row in rows]


async def untraced_functions(graph: _Graph) -> list[Node]:
    return await untraced_functions_limited(graph)


async def untraced_functions_limited(
    graph: _Graph,
    *,
    limit: int = 100,
    path_prefix: str | None = None,
) -> list[Node]:
    where_clause = f"f.kind IN ['function','method'] AND NOT ( (f)-[:{_LOOM_IMPL_REL}]->() )"
    params: dict[str, Any] = {"limit": limit}
    if path_prefix is not None:
        where_clause += " AND f.path STARTS WITH $path_prefix"
        params["path_prefix"] = path_prefix
    rows = await graph.query(
        f"MATCH (f {{source: 'code'}}) WHERE {where_clause} RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata LIMIT $limit",
        params,
    )
    return [_row_to_code_node(row) for row in rows]


async def impact_of_ticket(ticket_id: str, graph: _Graph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (f)-[:{_LOOM_IMPL_REL}]->(t) WHERE t.name = $ticket_id OR t.id = $ticket_id RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata",
        {"ticket_id": ticket_id},
    )
    return [_row_to_code_node(row) for row in rows]


async def tickets_for_function(node_id: str, graph: _Graph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (f {{id: $node_id}})-[:{_LOOM_IMPL_REL}]->(t) WHERE t.path STARTS WITH 'jira://' RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
        {"node_id": node_id},
    )
    return [_row_to_doc_node(row) for row in rows]


async def sprint_code_coverage(sprint_name: str, graph: _Graph) -> TraceCoverageReport:
    rows = await graph.query(
        f"MATCH (f)-[:{_LOOM_IMPL_REL}]->(t) WHERE t.path STARTS WITH 'jira://' AND t.metadata.sprint = $sprint_name RETURN count(DISTINCT t) AS ticket_count, count(DISTINCT f) AS linked_function_count",
        {"sprint_name": sprint_name},
    )
    row = rows[0] if rows else {}
    return TraceCoverageReport(
        sprint_name=sprint_name,
        ticket_count=int(row.get("ticket_count") or 0),
        linked_function_count=int(row.get("linked_function_count") or 0),
    )
