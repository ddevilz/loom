"""analysis.py — analysis, annotation, and savings MCP tools."""
from __future__ import annotations


def register(mcp: object, db: object, session: dict, cache: object) -> None:
    from loom.intelligence.cohesion import get_community_cohesion as _get_cohesion  # noqa: F401
    from loom.intelligence.surprising_connections import get_surprising_connections as _get_surprising
    from loom.intelligence.suggested_questions import suggest_questions as _suggest_questions
    from loom.store import nodes as node_store
    from loom.store.node_visits import get_annotation_gaps
    from loom.store.savings import get_recent_savings, get_savings_stats

    from loom.server.enums import ErrorCode, WorkPlanPriority
    from loom.server.validation import MAX_ID, clamp_limit, err, ok, validate_text

    @mcp.tool()
    async def store_understanding_batch(updates: list[dict]) -> dict:
        """Cache summaries for multiple nodes in one call. Max 50 per call."""
        batch = updates[:50]
        stored = skipped = 0
        errors: list[dict] = []
        for item in batch:
            nid = str(item.get("node_id", "")).strip()
            s = str(item.get("summary", "")).strip()
            force = bool(item.get("force", False))
            if not nid or not s:
                errors.append(
                    {
                        "node_id": nid or "(blank)",
                        "error_code": ErrorCode.VALIDATION_ERROR,
                    }
                )
                continue
            r = await node_store.update_summary(
                db,
                nid,
                s,
                force=force,
                author=session.get("agent_id"),
                session_id=session.get("id"),
            )
            if not r["found"]:
                errors.append({"node_id": nid, "error_code": ErrorCode.NODE_NOT_FOUND})
            elif r["updated"]:
                cache.invalidate(nid)
                stored += 1
            else:
                skipped += 1
        return ok({"stored": stored, "skipped": skipped, "total": len(batch), "errors": errors})

    @mcp.tool()
    async def store_understanding(
        node_id: str,
        summary: str,
        force: bool = False,
        tags: list[str] | None = None,
    ) -> dict:
        """Persist agent-generated understanding of a node back into the graph.

        Skips write if a summary already exists and the function has not changed
        since it was last stored (content_hash unchanged). Pass force=True to
        overwrite an existing summary regardless.

        tags: Optional list of agent tags to attach to this node (e.g. ["security-sensitive", "needs-refactor"]).
              Tags are persisted with source="agent" and survive re-index.

        Returns {"ok": true, "skipped": true} when skipped — no re-read needed.
        """
        try:
            nid = validate_text(node_id, field="node_id", max_length=MAX_ID)
            s = validate_text(summary, field="summary", max_length=4000)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        result = await node_store.update_summary(
            db,
            nid,
            s,
            force=force,
            author=session.get("agent_id"),
            session_id=session.get("id"),
        )
        if not result["found"]:
            return err(
                ErrorCode.NODE_NOT_FOUND,
                f"Node '{nid}' not found.",
                "Use search_code() to find the correct ID.",
            )
        if result["updated"]:
            cache.invalidate(nid)

        # Write agent tags if provided
        tags_written = 0
        tags_rejected = 0
        if tags:
            raw_count = len(tags)
            valid_tags = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
            tags_rejected = raw_count - len(valid_tags)
            if valid_tags:
                import asyncio  # noqa: PLC0415
                from loom.graph.repository.tags import TagRepository  # noqa: PLC0415

                def _write_tags() -> int:
                    TagRepository(db).add_tags(nid, valid_tags, source="agent")
                    return len(valid_tags)

                tags_written = await asyncio.to_thread(_write_tags)

        return ok({"skipped": result["skipped"], "node_id": nid, "tags_written": tags_written, "tags_rejected": tags_rejected})

    @mcp.tool()
    async def get_savings() -> dict:
        """Report tokens saved by Loom cache hits — all-time and recent.

        agent_hits: summaries written by you (store_understanding) — file reads provably skipped.
        auto_hits: structural summaries from analyze — may still need source for full context.
        """
        stats = await get_savings_stats(db)
        recent = await get_recent_savings(db, limit=10)
        return ok({**stats, "recent": recent})

    @mcp.tool()
    async def get_surprising_connections(limit: int = 10) -> dict:
        """Find non-obvious CALLS edges — cross-community, peripheral-to-hub, cross-module.

        Ranked by composite surprise score. Each result includes human-readable
        reasons explaining what makes it non-obvious.

        Useful for: discovering hidden coupling, unexpected dependencies,
        functions that act as unofficial bridges between subsystems.
        """
        return ok(await _get_surprising(db, limit=clamp_limit(limit)))

    @mcp.tool()
    async def suggest_questions(limit: int = 7) -> dict:
        """Generate questions worth investigating based on graph topology.

        Question types:
        - dead_code: functions with no callers (unused or missing edges)
        - bridge_node: functions serving multiple communities (possible god function)
        - missing_summary: hot functions with no cached summary (high documentation value)
        - low_cohesion: communities whose members mostly call outside (refactor candidate)

        Call this at session start to prioritize what to investigate.
        """
        return ok(await _suggest_questions(db, limit=clamp_limit(limit)))

    @mcp.tool()
    async def get_work_plan() -> dict:
        """One-call session bootstrap — priority, reason, and concrete annotation tasks.

        Combines suggest_questions + annotation_gaps + live graph stats to compute
        the highest-value action for this session.

        priority values:
        - DOCUMENT: high-traffic functions with no agent summary — annotate first
        - INVESTIGATE: structural issues (dead code, low cohesion, bridge nodes)
        - EXPLORE: graph is healthy — use suggest_questions to pick exploration targets
        - NOTHING: graph is fully annotated and structurally sound

        Replaces the primer → suggest_questions → god_nodes orientation sequence
        with a single call (~200 tokens).
        """
        import asyncio as _asyncio

        questions = await _suggest_questions(db, limit=7)
        gaps = await get_annotation_gaps(db, limit=5)

        def _stats() -> dict:
            with db._lock:
                conn = db.connect()
                total = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL "
                    "AND kind IN ('function','method')"
                ).fetchone()[0]
                annotated = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL "
                    "AND kind IN ('function','method') AND summary_hash IS NOT NULL"
                ).fetchone()[0]
                return {"total": total, "annotated": annotated}

        stats = await _asyncio.to_thread(_stats)
        total = stats["total"]
        annotated = stats["annotated"]
        coverage = round(annotated / total, 2) if total else 1.0

        missing_summary_qs = [q for q in questions if q.get("type") == "MISSING_SUMMARY"]
        structural_qs = [q for q in questions if q.get("type") != "MISSING_SUMMARY"]

        tasks: list[dict] = []
        if gaps:
            priority = WorkPlanPriority.DOCUMENT
            reason = (
                f"Summary coverage {int(coverage * 100)}% — "
                f"{len(gaps)} high-traffic function(s) re-read every session without stored understanding."  # noqa: E501
            )
            for g in gaps:
                tasks.append(
                    {
                        "action": "store_understanding",
                        "node_id": g["node_id"],
                        "name": g["name"],
                        "path": g["path"],
                        "reason": f"{g['visit_count']} total reads, no agent summary",
                    }
                )
        elif missing_summary_qs:
            priority = WorkPlanPriority.DOCUMENT
            reason = (
                f"Summary coverage {int(coverage * 100)}% — "
                f"{len(missing_summary_qs)} hot function(s) with only auto-summary."
            )
            for q in missing_summary_qs[:5]:
                tasks.append(
                    {
                        "action": "store_understanding",
                        "node_id": q.get("node_id"),
                        "name": q.get("name"),
                        "path": q.get("path"),
                        "reason": q.get("reason", "high in-degree, no agent summary"),
                    }
                )
        elif structural_qs:
            priority = WorkPlanPriority.INVESTIGATE
            reason = f"{len(structural_qs)} structural issue(s) worth investigating."
            for q in structural_qs[:5]:
                tasks.append(
                    {
                        "action": "investigate",
                        "type": q.get("type"),
                        "node_id": q.get("node_id"),
                        "name": q.get("name"),
                        "reason": q.get("reason"),
                    }
                )
        elif coverage < 1.0:
            priority = WorkPlanPriority.EXPLORE
            reason = (
                f"Graph healthy — {int(coverage * 100)}% annotated. "
                "Use suggest_questions for exploration targets."
            )
        else:
            priority = WorkPlanPriority.NOTHING
            reason = "Graph fully annotated and structurally sound."

        return ok(
            {
                "priority": priority,
                "reason": reason,
                "summary_coverage": coverage,
                "tasks": tasks,
                "session_id": session.get("id"),
            }
        )
