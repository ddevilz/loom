from __future__ import annotations

from loom.core import LoomGraph
from loom.query.traceability import (
    get_functions_for_ticket,
    get_tickets_for_symbol,
    get_orphan_functions as _query_orphan_functions,
    unimplemented_tickets,
)

_MAX_IDENTIFIER_LENGTH = 512


def _require_non_empty_text(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be <= {max_length} characters")
    return normalized


def register_ticket_tools(mcp, graph: LoomGraph) -> None:
    """Register all ticket-related MCP tools onto the given FastMCP instance."""

    @mcp.tool()
    async def get_ticket_implementation(ticket_id: str) -> list[dict[str, object]]:
        """Return all code functions that implement a ticket.

        Traverses LOOM_IMPLEMENTS, REALIZES, and CLOSES edges from any code
        node pointing at this ticket. Works for GitHub Issues, Jira, and Linear.
        Use this to understand what code was written for a specific ticket.

        Args:
            ticket_id: Ticket key (e.g. "PROJ-42", "#42") or full node id.
        """
        ticket_id = _require_non_empty_text(
            ticket_id, field_name="ticket_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        nodes = await get_functions_for_ticket(ticket_id, graph)
        return [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "kind": n.kind.value,
                "summary": n.summary,
            }
            for n in nodes
        ]

    @mcp.tool()
    async def get_ticket_for_symbol(symbol_name: str) -> list[dict[str, object]]:
        """Return tickets linked to a code function or class.

        Finds tickets this symbol was written to implement, by traversing
        outgoing LOOM_IMPLEMENTS, REALIZES, and CLOSES edges. Works for
        any ticket provider (GitHub, Jira, Linear).

        Args:
            symbol_name: Function or class name (e.g. "validate_user") or exact node id.
        """
        symbol_name = _require_non_empty_text(
            symbol_name, field_name="symbol_name", max_length=_MAX_IDENTIFIER_LENGTH
        )
        nodes = await get_tickets_for_symbol(symbol_name, graph)
        return [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "status": n.status,
                "url": n.url,
                "external_id": n.external_id,
                "summary": n.summary,
            }
            for n in nodes
        ]

    @mcp.tool()
    async def find_unimplemented_tickets(limit: int = 50) -> list[dict[str, object]]:
        """Return tickets that have no linked code symbols.

        A ticket is unimplemented when no function/class has a LOOM_IMPLEMENTS,
        REALIZES, or CLOSES edge pointing to it. Covers both GitHub Issues and Jira.
        Use this to find spec gaps or missing implementations.

        Args:
            limit: Maximum results to return (1-100, default 50).
        """
        nodes = await unimplemented_tickets(graph)
        limit = max(1, min(limit, 100))
        return [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "status": n.status,
                "url": n.url,
                "summary": n.summary,
            }
            for n in nodes[:limit]
        ]

    @mcp.tool()
    async def get_orphan_functions(
        limit: int = 50,
        path_prefix: str | None = None,
    ) -> list[dict[str, object]]:
        """Return functions with no linked ticket (undocumented work).

        An orphan function has no outgoing LOOM_IMPLEMENTS, REALIZES, or CLOSES
        edge to any ticket. These represent code written without a corresponding
        ticket — either undocumented features or unlinked historical work.

        Args:
            limit: Maximum results (1-100, default 50).
            path_prefix: Optional file path prefix to restrict the search (e.g. "src/auth/").
        """
        limit = max(1, min(limit, 100))
        nodes = await _query_orphan_functions(graph, limit=limit, path_prefix=path_prefix)
        return [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "kind": n.kind.value,
                "summary": n.summary,
            }
            for n in nodes
        ]
