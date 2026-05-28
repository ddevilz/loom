"""context.py — get_context MCP tool."""

from __future__ import annotations


def register(mcp: object, db: object, session: dict, cache: object) -> None:
    from loom.graph.models import SummarySource
    from loom.query.context import get_context_packet
    from loom.server.enums import ErrorCode
    from loom.server.validation import MAX_ID, err, ok, validate_text

    async def _log(node_id: str, tool: str) -> None:
        from loom.store.node_visits import log_visit

        sid = session.get("id")
        if sid:
            await log_visit(db, session_id=sid, node_id=node_id, tool=tool)

    @mcp.tool()
    async def get_context(
        node_id: str,
        brief: bool = False,
        callers_limit: int = 10,
        callees_limit: int = 10,
    ) -> dict:
        """Full context packet — everything to reason about a function without reading source.

        Returns summary, signature, callers, callees, and staleness flag.
        If summary_stale is True, check auto_summary for current metadata.
        For class/file nodes, returns members instead of callers/callees.

        Replaces get_node (brief=True) and get_callers/get_callees (callers_limit/callees_limit).

        Args:
            node_id: Exact node id from search_code results.
                     Example: 'function:src/auth.py:validate_token'
            brief: Return metadata only (id/name/path/kind/language/lines) — no traversal.
                   Faster than full context when you only need to check existence.
            callers_limit: Max callers to return (0 = skip callers, saves ~50% response size).
            callees_limit: Max callees to return (0 = skip callees).
        """
        try:
            nid = validate_text(node_id, field="node_id", max_length=MAX_ID)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        await _log(nid, "get_context")
        key = cache.make_key("get_context", nid, brief=brief, cl=callers_limit, ce=callees_limit)
        if (hit := cache.get(key)) is not None:
            return hit
        packet = await get_context_packet(
            db, nid, brief=brief, callers_limit=callers_limit, callees_limit=callees_limit
        )
        if not brief and packet and packet.get("summary_source") == SummarySource.AUTO:
            packet["_nudge"] = (
                f"No agent understanding stored for '{nid}'. "
                f"After reading, call store_understanding(node_id='{nid}', "
                f"summary='your interpretation')."
            )
        result = ok(packet)
        cache.set(key, result)
        return result
