from __future__ import annotations

import logging
from pathlib import Path

from loom.analysis.graph_insights import (
    get_community_cohesion as _get_community_cohesion,
)
from loom.analysis.graph_insights import (
    get_surprising_connections as _get_surprising_connections,
)
from loom.analysis.graph_insights import (
    suggest_questions as _suggest_questions,
)
from loom.core.context import DB, DEFAULT_DB_PATH
from loom.core.edge import EdgeType
from loom.core.enums import SummarySource
from loom.mcp import run as _run_mod
from loom.mcp.enums import ErrorCode
from loom.query import traversal
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.context import get_context_packet
from loom.query.delta import get_delta_payload
from loom.query.primer import build_primer
from loom.query.search import search
from loom.store import nodes as node_store
from loom.store.savings import get_recent_savings, get_savings_stats, log_saving
from loom.store.sessions import create_session, get_latest_session_for_agent, get_session

logger = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore

_MAX_QUERY = 1000
_MAX_ID = 512


def _clamp_limit(n: int) -> int:
    return max(1, min(n, 100))


def _clamp_depth(d: int) -> int:
    return max(1, min(d, 10))


def _req_text(value: str, *, field: str, max_length: int) -> str:
    v = value.strip()
    if not v:
        raise ValueError(f"{field} must be non-empty")
    if len(v) > max_length:
        raise ValueError(f"{field} must be <= {max_length} characters")
    return v


def _ok(data: object) -> dict:
    return {"ok": True, "data": data}


def _err(error_code: ErrorCode, message: str, suggestion: str | None = None) -> dict:
    result: dict = {"ok": False, "error_code": error_code, "message": message}
    if suggestion is not None:
        result["suggestion"] = suggestion
    return result


def build_server(
    db_path: Path | None = None,
    *,
    db: DB | None = None,
) -> FastMCP:
    """Build and return the FastMCP server with all 20 tools registered."""
    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")
    if db is None:
        db = DB(path=db_path or DEFAULT_DB_PATH)

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> dict:
        """Search nodes by name/summary/path via FTS5 or LIKE.

        Returns summary and signature when available — if summary exists,
        you may not need to read the source file at all.
        The tokens_saved field shows how many tokens Loom saved by returning
        a cached summary instead of requiring you to read the source file.
        """
        q = _req_text(query, field="query", max_length=_MAX_QUERY)
        results = await search(q, db, limit=_clamp_limit(limit))

        output = []
        for r in results:
            node = r.node
            tokens_saved = 0
            summary_type = None

            if node.summary:
                # summary_hash set → store_understanding wrote it → agent-verified
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

            result: dict = {
                "id": node.id,
                "name": node.name,
                "path": node.path,
                "kind": node.kind.value,
                "line": node.start_line,
                "score": r.score,
                "summary": node.summary,
                "signature": node.metadata.get("signature"),
            }
            if tokens_saved > 0:
                result["tokens_saved"] = tokens_saved
                result["summary_type"] = summary_type
            output.append(result)

        return _ok(output)

    @mcp.tool()
    async def get_node(node_id: str) -> dict:
        """Return a single node by id."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        n = await node_store.get_node(db, nid)
        return _ok(None if n is None else {
            "id": n.id,
            "name": n.name,
            "path": n.path,
            "kind": n.kind.value,
            "language": n.language,
            "summary": n.summary,
            "start_line": n.start_line,
            "end_line": n.end_line,
        })

    @mcp.tool()
    async def get_callers(node_id: str) -> dict:
        """One-hop incoming CALLS — functions that call this node."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="in"
        )
        return _ok([
            {"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes
        ])

    @mcp.tool()
    async def get_callees(node_id: str) -> dict:
        """One-hop outgoing CALLS — functions this node calls."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="out"
        )
        return _ok([
            {"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes
        ])

    @mcp.tool()
    async def get_blast_radius(
        node_id: str, depth: int = 3, limit: int = 50, offset: int = 0
    ) -> dict:
        """Transitive callers via SQLite recursive CTE. Paginated."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        limit = max(1, min(limit, 200))
        return _ok(await build_blast_radius_payload(
            db, node_id=nid, depth=_clamp_depth(depth), limit=limit, offset=offset
        ))

    @mcp.tool()
    async def get_neighbors(node_id: str, depth: int = 1) -> dict:
        """Generic neighbor traversal across all edge kinds, both directions."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(db, nid, depth=_clamp_depth(depth))
        return _ok([
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value, "summary": n.summary}
            for n in nodes
        ])

    @mcp.tool()
    async def get_community(community_id: str) -> dict:
        """Return all member nodes of a community cluster."""
        cid = _req_text(community_id, field="community_id", max_length=_MAX_ID)
        nodes = await traversal.community_members(db, cid)
        return _ok([
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value, "summary": n.summary}
            for n in nodes
        ])

    @mcp.tool()
    async def shortest_path(from_id: str, to_id: str) -> dict:
        """Shortest directed path on CALLS subgraph."""
        fid = _req_text(from_id, field="from_id", max_length=_MAX_ID)
        tid = _req_text(to_id, field="to_id", max_length=_MAX_ID)
        path = await traversal.shortest_path(db, fid, tid)
        return _ok(
            None if path is None
            else [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in path]
        )

    @mcp.tool()
    async def graph_stats() -> dict:
        """Node/edge counts broken down by kind."""
        return _ok(await traversal.stats(db))

    @mcp.tool()
    async def god_nodes(limit: int = 20) -> dict:
        """Highest in-degree on CALLS subgraph (most-called functions)."""
        pairs = await traversal.god_nodes(db, _clamp_limit(limit))
        return _ok([
            {"id": n.id, "name": n.name, "path": n.path, "in_degree": deg, "summary": n.summary}
            for n, deg in pairs
        ])

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
                errors.append({
                    "node_id": nid or "(blank)",
                    "error_code": ErrorCode.VALIDATION_ERROR,
                })
                continue
            r = await node_store.update_summary(db, nid, s, force=force)
            if not r["found"]:
                errors.append({"node_id": nid, "error_code": ErrorCode.NODE_NOT_FOUND})
            elif r["updated"]:
                stored += 1
            else:
                skipped += 1
        return _ok({"stored": stored, "skipped": skipped, "total": len(batch), "errors": errors})

    @mcp.tool()
    async def store_understanding(node_id: str, summary: str, force: bool = False) -> dict:
        """Persist agent-generated understanding of a node back into the graph.

        Skips write if a summary already exists and the function has not changed
        since it was last stored (content_hash unchanged). Pass force=True to
        overwrite an existing summary regardless.

        Returns {"ok": true, "skipped": true} when skipped — no re-read needed.
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        s = _req_text(summary, field="summary", max_length=4000)
        result = await node_store.update_summary(db, nid, s, force=force)
        if not result["found"]:
            return _err(
                ErrorCode.NODE_NOT_FOUND,
                f"Node '{nid}' not found.",
                "Use search_code() to find the correct ID.",
            )
        return _ok({"skipped": result["skipped"], "node_id": nid})

    @mcp.tool()
    async def get_savings() -> dict:
        """Report tokens saved by Loom cache hits — all-time and recent.

        agent_hits: summaries written by you (store_understanding) — file reads provably skipped.
        auto_hits: structural summaries from analyze — may still need source for full context.
        """
        stats = await get_savings_stats(db)
        recent = await get_recent_savings(db, limit=10)
        return _ok({
            **stats,
            "recent": recent,
            "note": "tokens_saved estimated from source line counts (15 tokens/line avg)",
        })

    @mcp.tool()
    async def get_context(node_id: str) -> dict:
        """Full context packet — everything to reason about a function without reading source.

        Returns summary, signature, callers (top 10), callees (top 10), and staleness flag.
        If summary_stale is True, check auto_summary for current metadata.
        For class/file nodes, returns members instead of callers/callees.

        Args:
            node_id: Exact node id from search_code results.
                     Example: 'function:src/auth.py:validate_token'
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        packet = await get_context_packet(db, nid)
        return _ok(packet)

    @mcp.tool()
    async def start_session(agent_id: str = "default") -> dict:
        """Register start of agent session. Call once at session beginning.

        Returns session_id — store it and pass to get_delta in your NEXT session.

        Args:
            agent_id: Consistent identifier for your agent type.
                      Use: 'claude-code', 'cursor', 'codex', 'windsurf', or custom.
        """
        aid = _req_text(agent_id, field="agent_id", max_length=64)
        result = await create_session(db, agent_id=aid)
        result["tip"] = "Store session_id and pass to get_delta() in your next session."
        return _ok(result)

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
            return _err(ErrorCode.MISSING_ARGS, "Provide either previous_session_id or agent_id.")

        session_row = None
        if previous_session_id:
            pid = _req_text(previous_session_id, field="previous_session_id", max_length=64)
            session_row = await get_session(db, pid)
            if session_row is None:
                return _err(
                    ErrorCode.SESSION_NOT_FOUND,
                    f"Session '{pid}' not found.",
                    "Use agent_id= to find your latest session instead.",
                )
        else:
            aid = _req_text(agent_id, field="agent_id", max_length=64)  # type: ignore[arg-type]
            session_row = await get_latest_session_for_agent(db, aid)
            if session_row is None:
                return _err(
                    ErrorCode.NO_PRIOR_SESSION,
                    f"No previous session found for agent_id '{agent_id}'.",
                    "Call start_session() at the beginning of each session.",
                )

        return _ok(await get_delta_payload(db, since_ts=session_row["started_at"]))

    @mcp.tool()
    async def get_surprising_connections(limit: int = 10) -> dict:
        """Find non-obvious CALLS edges — cross-community, peripheral-to-hub, cross-module.

        Ranked by composite surprise score. Each result includes human-readable
        reasons explaining what makes it non-obvious.

        Useful for: discovering hidden coupling, unexpected dependencies,
        functions that act as unofficial bridges between subsystems.
        """
        return _ok(await _get_surprising_connections(db, limit=_clamp_limit(limit)))

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
        return _ok(await _suggest_questions(db, limit=_clamp_limit(limit)))

    @mcp.tool()
    async def get_community_cohesion() -> dict:
        """Cohesion score for every community.

        Cohesion = internal CALLS / (internal + external CALLS).
        1.0 = perfectly self-contained. 0.0 = all calls cross boundaries.

        Low cohesion (<0.2) communities are refactor candidates.
        """
        return _ok(await _get_community_cohesion(db))

    @mcp.tool()
    async def get_status() -> dict:
        """Live indexing progress + DB stats.

        Call at session start to check if auto-index is still running.
        Also returns node count, FTS5 availability, and DB path.
        """
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

        import asyncio as _asyncio
        stats = await _asyncio.to_thread(_query)
        progress = _run_mod._index_progress

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

        return _ok(data)

    @mcp.resource("loom://savings")
    async def savings_resource() -> str:
        """Token savings report — how much Loom has saved across all sessions."""
        stats = await get_savings_stats(db)
        recent = await get_recent_savings(db, limit=5)
        lines = [
            "# Loom Token Savings",
            f"Total saved : {stats['total_tokens_saved']:,} tokens",
            f"Cache hits  : {stats['total_hits']:,}  "
            f"(agent: {stats['agent_hits']}, auto: {stats['auto_hits']})",
            "",
            "## Recent hits",
        ]
        for r in recent:
            lines.append(
                f"- {r['node_id'].split(':')[-1]}  "
                f"+{r['tokens_saved']} tokens  [{r['summary_type']}]"
            )
        if not recent:
            lines.append("None yet — run loom analyze and search_code to start tracking.")
        return "\n".join(lines)

    @mcp.resource("loom://primer")
    async def primer_resource() -> str:
        """Compressed codebase overview — load at session start.

        Returns ~200-token summary: repo shape, modules, hot functions, coverage stats.
        Replaces cold-start file exploration (saves 3,000–10,000 tokens per session).
        """
        result = await build_primer(db)
        return str(result)

    @mcp.resource("loom://status")
    async def status_resource() -> str:
        """Live DB status — node count, indexing state, last analyzed."""
        import asyncio as _asyncio
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
        progress = _run_mod._index_progress
        indexing = progress.get("indexing", False)

        last_analyzed_ago = "never"
        if stats["last_ts"]:
            ago_s = int(time.time() - stats["last_ts"])
            if ago_s < 60:
                last_analyzed_ago = "just now"
            elif ago_s < 3600:
                last_analyzed_ago = f"{ago_s // 60}m ago"
            elif ago_s < 86400:
                last_analyzed_ago = f"{ago_s // 3600}h ago"
            else:
                last_analyzed_ago = f"{ago_s // 86400}d ago"

        lines = [
            "# Loom Status",
            f"Nodes       : {stats['node_count']:,}",
            f"Last indexed: {last_analyzed_ago}",
            f"Indexing    : {'yes (background)' if indexing else 'no'}",
            f"FTS5        : {'yes' if db._fts5 else 'no'}",
            f"DB          : {db.path}",
        ]
        if indexing:
            done = progress.get("files_processed", 0)
            total = progress.get("files_total", 0)
            lines.append(f"Progress    : {done}/{total} files ({progress.get('phase', '')})")
        return "\n".join(lines)

    return mcp
