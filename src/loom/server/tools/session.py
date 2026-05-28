"""session.py — session management and status MCP tools."""

from __future__ import annotations


def register(mcp: object, db: object, session: dict, run_mod: object) -> None:
    from loom.query.delta import get_delta_payload
    from loom.server.enums import ErrorCode
    from loom.server.validation import err, ok, validate_text
    from loom.store.node_visits import get_annotation_gaps, get_unannotated_reads
    from loom.store.sessions import create_session, get_latest_session_for_agent, get_session

    @mcp.tool()
    async def start_session(agent_id: str = "default") -> dict:
        """Register start of agent session. Call once at session beginning.

        Returns:
          - session_id: pass to get_delta() next session.
          - unannotated_reads: nodes you read last session without storing understanding
            (no agent summary, or summary stale because code changed). Annotate these first.
          - annotation_gaps: top nodes by total visit count across all sessions still lacking
            agent understanding — highest value annotation targets.

        Args:
            agent_id: Consistent identifier for your agent type.
                      Use: 'claude-code', 'cursor', 'codex', 'windsurf', or custom.
        """
        try:
            aid = validate_text(agent_id, field="agent_id", max_length=64)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))

        prev = await get_latest_session_for_agent(db, aid)

        result = await create_session(db, agent_id=aid)
        session["id"] = result["session_id"]
        session["agent_id"] = aid

        unannotated: list[dict] = []
        if prev:
            unannotated = await get_unannotated_reads(db, prev["id"])

        gaps = await get_annotation_gaps(db, limit=5)

        result["unannotated_reads"] = unannotated
        result["annotation_gaps"] = gaps
        if unannotated:
            result["_note"] = (
                f"{len(unannotated)} node(s) read last session without stored understanding. "
                "Annotate via store_understanding() before proceeding."
            )
        return ok(result)

    @mcp.tool()
    async def get_delta(
        previous_session_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict:
        """What changed since your last session — skip re-reading unchanged functions.

        Call at session start to get only what changed since you were last here.
        Returns context packets for changed/deleted nodes only.
        If too many changes (>100 nodes), returns summary with top changed paths.

        Args:
            previous_session_id: session_id from previous start_session call (most precise).
            agent_id: Find most recent session for this agent type (fallback).
        """
        if not previous_session_id and not agent_id:
            return err(ErrorCode.MISSING_ARGS, "Provide either previous_session_id or agent_id.")

        session_row = None
        if previous_session_id:
            try:
                pid = validate_text(previous_session_id, field="previous_session_id", max_length=64)
            except ValueError as exc:
                return err(ErrorCode.VALIDATION_ERROR, str(exc))
            session_row = await get_session(db, pid)
            if session_row is None:
                return err(
                    ErrorCode.SESSION_NOT_FOUND,
                    f"Session '{pid}' not found.",
                    "Use agent_id= to find your latest session instead.",
                )
        else:
            try:
                aid = validate_text(agent_id, field="agent_id", max_length=64)  # type: ignore[arg-type]
            except ValueError as exc:
                return err(ErrorCode.VALIDATION_ERROR, str(exc))
            session_row = await get_latest_session_for_agent(db, aid)
            if session_row is None:
                return err(
                    ErrorCode.NO_PRIOR_SESSION,
                    f"No previous session found for agent_id '{agent_id}'.",
                    "Call start_session() at the beginning of each session.",
                )

        return ok(await get_delta_payload(db, since_ts=session_row["started_at"]))

    @mcp.tool()
    async def get_status() -> dict:
        """Live indexing progress + DB stats.

        Call at session start to check if auto-index is still running.
        Also returns node count, FTS5 availability, and DB path.
        """
        import asyncio as _asyncio
        import datetime
        import time

        def _query() -> dict:
            with db._lock:
                conn = db.connect()
                node_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
                ).fetchone()[0]
                last_row = conn.execute(
                    "SELECT MAX(updated_at) AS ts FROM nodes WHERE deleted_at IS NULL"
                ).fetchone()
                last_ts = last_row["ts"] if last_row else None
            return {"node_count": node_count, "last_ts": last_ts}

        stats = await _asyncio.to_thread(_query)
        progress = run_mod._index_progress  # type: ignore[attr-defined]

        last_analyzed: str | None = None
        last_analyzed_ago: str | None = None
        if stats["last_ts"]:
            ts = stats["last_ts"]
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            last_analyzed = dt.isoformat()
            ago_s = int(time.time() - ts)
            if ago_s < 60:
                last_analyzed_ago = "just now"
            elif ago_s < 3600:
                last_analyzed_ago = f"{ago_s // 60}m"
            elif ago_s < 86400:
                last_analyzed_ago = f"{ago_s // 3600}h"
            else:
                last_analyzed_ago = f"{ago_s // 86400}d"

        fts5 = db._fts5 if db._fts5 is not None else False

        data: dict = {
            "indexing": progress.get("indexing", False),
            "node_count": stats["node_count"],
            "last_analyzed": last_analyzed,
            "last_analyzed_ago": last_analyzed_ago,
            "fts5_available": fts5,
            "db_path": str(db.path),
        }
        if progress.get("indexing"):
            data["files_processed"] = progress.get("files_processed", 0)
            data["files_total"] = progress.get("files_total", 0)
            data["phase"] = progress.get("phase", "unknown")

        return ok(data)
