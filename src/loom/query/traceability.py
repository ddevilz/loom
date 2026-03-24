from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import logging

from loom.core import Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import (
    CALLS_REL,
    LOOM_IMPLEMENTS_REL,
    LOOM_VIOLATES_REL,
    EdgeTypeAdapter,
)
from loom.core.edge import EdgeType
from loom.core.falkor.mappers import coerce_row_node_kind, row_to_node
from loom.core.protocols import QueryGraph

logger = logging.getLogger(__name__)

REALIZES_REL: str = EdgeTypeAdapter.to_storage(EdgeType.REALIZES)
CLOSES_REL: str = EdgeTypeAdapter.to_storage(EdgeType.CLOSES)
VERIFIED_BY_REL: str = EdgeTypeAdapter.to_storage(EdgeType.VERIFIED_BY)


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


def _row_to_ticket_or_doc_node(row: dict[str, Any]) -> Node | None:
    """Try to deserialize a row as a ticket node first, then as a doc node.

    New first-class ticket nodes have source='ticket' and id starting with 'ticket:'.
    Legacy Jira nodes have source='doc' and id starting with 'doc:'.
    We detect which format we're dealing with by inspecting the id prefix.
    """
    node_id = row.get("id")
    if isinstance(node_id, str) and node_id.startswith("ticket:"):
        node = row_to_node(
            row,
            source=NodeSource.TICKET,
            fallback_kind=NodeKind.TICKET,
            allowed_kinds={NodeKind.TICKET},
        )
        if node is not None:
            return node
    return _row_to_doc_node(row)


async def unimplemented_tickets(graph: QueryGraph) -> list[Node]:
    # Match both legacy jira:// nodes (source='doc') and new ticket nodes (source='ticket')
    rows = await graph.query(
        f"MATCH (t) WHERE (t.source = 'ticket' OR t.path STARTS WITH 'jira://') "
        f"AND NOT ( ()-[:{LOOM_IMPLEMENTS_REL}]->(t) ) "
        f"AND NOT ( ()-[:{REALIZES_REL}]->(t) ) "
        f"AND NOT ( ()-[:{CLOSES_REL}]->(t) ) "
        "RETURN t.id AS id, t.name AS name, t.summary AS summary, "
        "t.path AS path, t.kind AS kind, t.metadata AS metadata"
    )
    return [n for row in rows if (n := _row_to_ticket_or_doc_node(row)) is not None]


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
        f"MATCH (f)-[:{LOOM_IMPLEMENTS_REL}|{REALIZES_REL}|{CLOSES_REL}]->(t) "
        "WHERE t.name = $ticket_id OR t.id = $ticket_id OR t.external_id = $ticket_id "
        "RETURN f.id AS id, f.kind AS kind, f.name AS name, "
        "f.summary AS summary, f.path AS path, f.metadata AS metadata",
        {"ticket_id": ticket_id},
    )
    return [n for row in rows if (n := _row_to_code_node(row)) is not None]


async def tickets_for_function(node_id: str, graph: QueryGraph) -> list[Node]:
    rows = await graph.query(
        f"MATCH (f:Node {{id: $node_id}})-[:{LOOM_IMPLEMENTS_REL}|{REALIZES_REL}|{CLOSES_REL}]->(t:Node) "
        "WHERE t.source = 'ticket' OR t.path STARTS WITH 'jira://' "
        "RETURN t.id AS id, t.name AS name, t.summary AS summary, "
        "t.path AS path, t.kind AS kind, t.metadata AS metadata",
        {"node_id": node_id},
    )
    return [n for row in rows if (n := _row_to_ticket_or_doc_node(row)) is not None]


async def get_functions_for_ticket(ticket_id: str, graph: QueryGraph) -> list[Node]:
    """Return code nodes that implement a ticket via LOOM_IMPLEMENTS, REALIZES, or CLOSES edges.

    Works for both legacy Jira nodes and new first-class ticket nodes.

    Args:
        ticket_id: Ticket key (e.g. "PROJ-42", "#42") or full node id.
        graph: Graph to query.

    Returns:
        Code nodes that implement this ticket.
    """
    rows = await graph.query(
        f"MATCH (f)-[r:{LOOM_IMPLEMENTS_REL}|{REALIZES_REL}|{CLOSES_REL}]->(t) "
        "WHERE t.name = $ticket_id OR t.id = $ticket_id OR t.external_id = $ticket_id "
        "RETURN f.id AS id, f.kind AS kind, f.name AS name, "
        "f.summary AS summary, f.path AS path, f.metadata AS metadata",
        {"ticket_id": ticket_id},
    )
    return [n for row in rows if (n := _row_to_code_node(row)) is not None]


async def get_tickets_for_symbol(symbol_name: str, graph: QueryGraph) -> list[Node]:
    """Return tickets linked to a code symbol via LOOM_IMPLEMENTS, REALIZES, or CLOSES edges.

    Works for any ticket provider (GitHub, Jira, Linear).

    Args:
        symbol_name: Function/method/class name or exact node id.
        graph: Graph to query.

    Returns:
        Ticket nodes linked to this symbol.
    """
    rows = await graph.query(
        f"MATCH (f:Node)-[:{LOOM_IMPLEMENTS_REL}|{REALIZES_REL}|{CLOSES_REL}]->(t:Node) "
        "WHERE (f.name = $name OR f.id = $name) "
        "AND (t.source = 'ticket' OR t.path STARTS WITH 'jira://') "
        "RETURN t.id AS id, t.name AS name, t.summary AS summary, "
        "t.path AS path, t.kind AS kind, t.metadata AS metadata, "
        "t.status AS status, t.url AS url, t.external_id AS external_id",
        {"name": symbol_name},
    )
    return [n for row in rows if (n := _row_to_ticket_or_doc_node(row)) is not None]


async def get_orphan_functions(
    graph: QueryGraph,
    *,
    limit: int = 100,
    path_prefix: str | None = None,
) -> list[Node]:
    """Return code functions/methods with no linked ticket (undocumented work).

    A function is an 'orphan' when it has no outgoing LOOM_IMPLEMENTS, REALIZES,
    or CLOSES edges pointing to any ticket node. This surfaces code that was written
    without a corresponding ticket — either undocumented work or unlinked tickets.

    Args:
        graph: Graph to query.
        limit: Maximum results to return (default 100).
        path_prefix: Optional file path prefix to restrict the search.

    Returns:
        Code nodes with no ticket linkage.
    """
    where_parts = [
        "f.kind IN ['function','method']",
        f"NOT ( (f)-[:{LOOM_IMPLEMENTS_REL}]->() )",
        f"NOT ( (f)-[:{REALIZES_REL}]->() )",
        f"NOT ( (f)-[:{CLOSES_REL}]->() )",
    ]
    params: dict[str, Any] = {"limit": limit}
    if path_prefix is not None:
        where_parts.append("f.path STARTS WITH $path_prefix")
        params["path_prefix"] = path_prefix
    where_clause = " AND ".join(where_parts)
    rows = await graph.query(
        f"MATCH (f {{source: 'code'}}) WHERE {where_clause} "
        "RETURN f.id AS id, f.kind AS kind, f.name AS name, "
        "f.summary AS summary, f.path AS path, f.metadata AS metadata "
        "LIMIT $limit",
        params,
    )
    return [n for row in rows if (n := _row_to_code_node(row)) is not None]


async def callers_of_node(
    node_id: str,
    graph: QueryGraph,
) -> list[dict[str, object]]:
    return await graph.query(
        f"MATCH (a:Node)-[r:{CALLS_REL}]->(b:Node {{id: $id}}) "
        "RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
        {"id": node_id},
    )


async def ast_drift_rows_for_node(
    node_id: str,
    graph: QueryGraph,
) -> list[dict[str, object]]:
    return await graph.query(
        f"MATCH (f:Node {{id: $id}})-[r:{LOOM_VIOLATES_REL}]->() "
        "RETURN f.id AS node_id, r.link_method AS link_method, "
        "r.link_reason AS link_reason, r.metadata AS metadata",
        {"id": node_id},
    )


async def ticket_rows_by_id(
    ticket_id: str,
    graph: QueryGraph,
) -> list[dict[str, object]]:
    return await graph.query(
        "MATCH (t:Node) WHERE (t.name = $ticket_id OR t.id = $ticket_id OR t.external_id = $ticket_id) "
        "AND (t.source = 'ticket' OR t.path STARTS WITH 'jira://') "
        "RETURN t.id AS id, t.name AS name, t.summary AS summary, "
        "t.path AS path, t.metadata AS metadata, t.status AS status, "
        "t.url AS url, t.external_id AS external_id",
        {"ticket_id": ticket_id},
    )


async def sprint_code_coverage(
    sprint_name: str, graph: QueryGraph
) -> TraceCoverageReport:
    # Fetch all jira-linked pairs and filter by sprint in Python — FalkorDB
    # stores metadata as a JSON string so dot-notation property access fails.
    all_rows = await graph.query(
        f"MATCH (f)-[:{LOOM_IMPLEMENTS_REL}|{REALIZES_REL}|{CLOSES_REL}]->(t) "
        "WHERE (t.path STARTS WITH 'jira://' OR t.source = 'ticket') "
        "RETURN DISTINCT f.id AS function_id, t.id AS ticket_id, t.metadata AS metadata",
    )
    rows = []
    for row in all_rows:
        raw_meta = row.get("metadata")
        meta: dict[str, object] = {}
        if isinstance(raw_meta, str):
            try:
                import json

                meta = json.loads(raw_meta)
            except Exception as exc:
                logger.debug("Failed to parse sprint metadata JSON (%s): %r", exc, raw_meta[:200])
        elif isinstance(raw_meta, dict):
            meta = raw_meta
        if str(meta.get("sprint", "")).lower() == sprint_name.lower():
            rows.append(row)

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
