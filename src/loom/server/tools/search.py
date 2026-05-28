"""search.py — search_code MCP tool."""

from __future__ import annotations


def _is_test_path(path: str) -> bool:
    p = path.lower()
    return "/test" in p or p.startswith("test")


def register(mcp: object, db: object, session: dict, cache: object) -> None:
    from loom.graph.models import SummarySource
    from loom.query.search import find_replacement_candidates, search
    from loom.server.validation import (
        MAX_QUERY,
        clamp_limit,
        compute_confidence,
        err,
        ok,
        validate_text,
    )
    from loom.store.savings import log_saving

    async def _log(node_id: str, tool: str) -> None:
        from loom.store.node_visits import log_visit

        sid = session.get("id")
        if sid:
            await log_visit(db, session_id=sid, node_id=node_id, tool=tool)

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> dict:
        """Search nodes by name/summary/path via FTS5 or LIKE.

        Results include caller_count and community_id for disambiguation.
        Dead nodes are ranked last with replacement_candidates where detectable.
        Test-file nodes are deprioritised (score penalty applied).
        Nodes that are dead but have a live replacement are injected with suggested_instead=true.
        """

        try:
            q = validate_text(query, field="query", max_length=MAX_QUERY)
        except ValueError as exc:
            from loom.server.enums import ErrorCode

            return err(ErrorCode.VALIDATION_ERROR, str(exc))

        raw = await search(q, db, limit=clamp_limit(limit))

        for r in raw:
            if _is_test_path(r.node.path):
                r.score *= 0.3

        live = sorted(
            raw,
            key=lambda r: r.score,
            reverse=True,
        )
        dead: list = []

        seen_ids: set[str] = set()
        output: list[dict] = []
        max_score = max((r.score for r in raw), default=1.0) or 1.0

        async def _build_entry(r: object, *, suggested_instead: bool = False) -> dict:  # type: ignore[type-arg]
            node = r.node  # type: ignore[attr-defined]
            tokens_saved = 0
            summary_type = None

            if node.summary:
                summary_type = SummarySource.AGENT if node.summary_hash else SummarySource.AUTO
                src_tokens = node.token_count or 0
                summary_tokens = len(node.summary) // 4
                tokens_saved = max(0, src_tokens - summary_tokens)
                if tokens_saved > 0:
                    await log_saving(
                        db,
                        node_id=node.id,
                        query=q,
                        tokens_saved=tokens_saved,
                        summary_type=summary_type,
                    )

            confidence, signals = compute_confidence(
                q,
                node.name,
                node.path,
                score=r.score,  # type: ignore[attr-defined]
                max_score=max_score,
                has_agent_summary=bool(node.summary_hash),
                caller_count=r.caller_count,  # type: ignore[attr-defined]
            )

            entry: dict = {
                "id": node.id,
                "name": node.name,
                "path": node.path,
                "kind": node.kind.value,
                "line": node.start_line,
                "score": round(r.score, 4),  # type: ignore[attr-defined]
                "confidence": confidence,
                "confidence_signals": signals,
                "caller_count": r.caller_count,  # type: ignore[attr-defined]
                "community_id": node.community_id,
                "summary": node.summary,
                "signature": node.metadata.get("signature"),
            }
            if suggested_instead:
                entry["suggested_instead"] = True
            if tokens_saved > 0:
                entry["tokens_saved"] = tokens_saved
                entry["summary_type"] = summary_type
            return entry

        for r in live:
            seen_ids.add(r.node.id)
            output.append(await _build_entry(r))

        for r in dead:
            seen_ids.add(r.node.id)
            entry = await _build_entry(r)
            candidates = await find_replacement_candidates(db, node_id=r.node.id, path=r.node.path)
            if candidates:
                entry["replacement_candidates"] = [
                    {"id": c.id, "name": c.name, "path": c.path, "caller_count": c.caller_count}
                    for c in candidates
                ]
                top = candidates[0]
                if top.id not in seen_ids:
                    seen_ids.add(top.id)
                    output.append(
                        {
                            "id": top.id,
                            "name": top.name,
                            "path": top.path,
                            "caller_count": top.caller_count,
                            "suggested_instead": True,
                            "suggested_for": r.node.id,
                        }
                    )
            output.append(entry)

        return ok(output)
