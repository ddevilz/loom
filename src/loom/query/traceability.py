from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.core import Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import LOOM_IMPLEMENTS_REL
from loom.core.falkor.mappers import coerce_row_node_kind, row_to_node
from loom.core.protocols import QueryGraph


@dataclass(frozen=True)
class TraceCoverageReport:
    sprint_name: str
    ticket_count: int
    linked_function_count: int


def _coerce_code_kind(raw_kind: Any) -> NodeKind:
    return (
        coerce_row_node_kind(
            raw_kind,
            fallback=NodeKind.FUNCTION,
            allowed_kinds={
                NodeKind.FUNCTION,
                NodeKind.METHOD,
                NodeKind.CLASS,
                NodeKind.INTERFACE,
                NodeKind.ENUM,
                NodeKind.TYPE,
                NodeKind.FILE,
            },
        )
        or NodeKind.FUNCTION
    )


def _coerce_doc_kind(raw_kind: Any) -> NodeKind:
    return (
        coerce_row_node_kind(
            raw_kind,
            fallback=NodeKind.SECTION,
            allowed_kinds={
                NodeKind.DOCUMENT,
                NodeKind.CHAPTER,
                NodeKind.SECTION,
                NodeKind.SUBSECTION,
                NodeKind.PARAGRAPH,
            },
        )
        or NodeKind.SECTION
    )


def _row_to_doc_node(row: dict[str, Any]) -> Node | None:
    allowed_doc_kinds = {
        NodeKind.DOCUMENT,
        NodeKind.CHAPTER,
        NodeKind.SECTION,
        NodeKind.SUBSECTION,
        NodeKind.PARAGRAPH,
    }
    return row_to_node(
        row,
        source=NodeSource.DOC,
        fallback_kind=_coerce_doc_kind(row.get("kind")),
        allowed_kinds=allowed_doc_kinds,
    )


def _row_to_code_node(row: dict[str, Any]) -> Node | None:
    allowed_code_kinds = {
        NodeKind.FUNCTION,
        NodeKind.METHOD,
        NodeKind.CLASS,
        NodeKind.INTERFACE,
        NodeKind.ENUM,
        NodeKind.TYPE,
        NodeKind.FILE,
    }
    return row_to_node(
        row,
        source=NodeSource.CODE,
        fallback_kind=_coerce_code_kind(row.get("kind")),
        allowed_kinds=allowed_code_kinds,
    )


async def unimplemented_tickets(graph: QueryGraph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (t {{source: 'doc'}}) WHERE t.path STARTS WITH 'jira://' AND NOT ( ()-[:{LOOM_IMPLEMENTS_REL}]->(t) ) RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata"
    )
    return [n for row in rows if (n := _row_to_doc_node(row)) is not None]


async def untraced_functions(graph: QueryGraph) -> list[Node]:
    return await untraced_functions_limited(graph)


async def untraced_functions_limited(
    graph: QueryGraph,
    *,
    limit: int = 100,
    path_prefix: str | None = None,
) -> list[Node]:
    where_clause = (
        f"f.kind IN ['function','method'] AND NOT ( (f)-[:{LOOM_IMPLEMENTS_REL}]->() )"
    )
    params: dict[str, Any] = {"limit": limit}
    if path_prefix is not None:
        where_clause += " AND f.path STARTS WITH $path_prefix"
        params["path_prefix"] = path_prefix
    rows = await graph.query(
        f"MATCH (f {{source: 'code'}}) WHERE {where_clause} RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata LIMIT $limit",
        params,
    )
    return [n for row in rows if (n := _row_to_code_node(row)) is not None]


async def impact_of_ticket(ticket_id: str, graph: QueryGraph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (f)-[:{LOOM_IMPLEMENTS_REL}]->(t) WHERE t.name = $ticket_id OR t.id = $ticket_id RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata",
        {"ticket_id": ticket_id},
    )
    return [n for row in rows if (n := _row_to_code_node(row)) is not None]


async def tickets_for_function(node_id: str, graph: QueryGraph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (f {{id: $node_id}})-[:{LOOM_IMPLEMENTS_REL}]->(t) WHERE t.path STARTS WITH 'jira://' RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
        {"node_id": node_id},
    )
    return [n for row in rows if (n := _row_to_doc_node(row)) is not None]


async def sprint_code_coverage(
    sprint_name: str, graph: QueryGraph
) -> TraceCoverageReport:
    rows = await graph.query(
        f"MATCH (f)-[:{LOOM_IMPLEMENTS_REL}]->(t) "
        "WHERE t.path STARTS WITH 'jira://' AND t.metadata.sprint = $sprint_name "
        "RETURN DISTINCT f.id AS function_id, t.id AS ticket_id",
        {"sprint_name": sprint_name},
    )

    matching_ticket_ids: set[str] = set()
    matching_function_ids: set[str] = set()
    for row in rows:
        ticket_id = row.get("ticket_id")
        function_id = row.get("function_id")
        if isinstance(ticket_id, str):
            matching_ticket_ids.add(ticket_id)
        if isinstance(function_id, str):
            matching_function_ids.add(function_id)

    return TraceCoverageReport(
        sprint_name=sprint_name,
        ticket_count=len(matching_ticket_ids),
        linked_function_count=len(matching_function_ids),
    )
