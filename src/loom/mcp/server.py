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


def build_server(
    db_path: Path | None = None,
    *,
    db: DB | None = None,
) -> FastMCP:
    """Build and return the FastMCP server with all 18 tools registered."""
    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")
    if db is None:
        db = DB(path=db_path or DEFAULT_DB_PATH)

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> list[dict]:
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
                summary_type = "agent" if node.summary_hash else "auto"
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

        return output

    @mcp.tool()
    async def get_node(node_id: str) -> dict | None:
        """Return a single node by id."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        n = await node_store.get_node(db, nid)
        if n is None:
            return None
        return {
            "id": n.id,
            "name": n.name,
            "path": n.path,
            "kind": n.kind.value,
            "language": n.language,
            "summary": n.summary,
            "start_line": n.start_line,
            "end_line": n.end_line,
        }

    @mcp.tool()
    async def get_callers(node_id: str) -> list[dict]:
        """One-hop incoming CALLS — functions that call this node."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="in"
        )
        return [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes]

    @mcp.tool()
    async def get_callees(node_id: str) -> list[dict]:
        """One-hop outgoing CALLS — functions this node calls."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="out"
        )
        return [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes]

    @mcp.tool()
    async def get_blast_radius(node_id: str, depth: int = 3) -> dict:
        """Transitive callers via SQLite recursive CTE."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        return await build_blast_radius_payload(db, node_id=nid, depth=_clamp_depth(depth))

    @mcp.tool()
    async def get_neighbors(node_id: str, depth: int = 1) -> list[dict]:
        """Generic neighbor traversal across all edge kinds, both directions."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await traversal.neighbors(db, nid, depth=_clamp_depth(depth))
        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value, "summary": n.summary}
            for n in nodes
        ]

    @mcp.tool()
    async def get_community(community_id: str) -> list[dict]:
        """Return all member nodes of a community cluster."""
        cid = _req_text(community_id, field="community_id", max_length=_MAX_ID)
        nodes = await traversal.community_members(db, cid)
        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value, "summary": n.summary}
            for n in nodes
        ]

    @mcp.tool()
    async def shortest_path(from_id: str, to_id: str) -> list[dict] | None:
        """Shortest directed path on CALLS subgraph."""
        fid = _req_text(from_id, field="from_id", max_length=_MAX_ID)
        tid = _req_text(to_id, field="to_id", max_length=_MAX_ID)
        path = await traversal.shortest_path(db, fid, tid)
        if path is None:
            return None
        return [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in path]

    @mcp.tool()
    async def graph_stats() -> dict:
        """Node/edge counts broken down by kind."""
        return await traversal.stats(db)

    @mcp.tool()
    async def god_nodes(limit: int = 20) -> list[dict]:
        """Highest in-degree on CALLS subgraph (most-called functions)."""
        pairs = await traversal.god_nodes(db, _clamp_limit(limit))
        return [
            {"id": n.id, "name": n.name, "path": n.path, "in_degree": deg, "summary": n.summary}
            for n, deg in pairs
        ]

    @mcp.tool()
    async def store_understanding_batch(updates: list[dict]) -> dict:
        """Cache summaries for multiple nodes in one call. Max 50 per call."""
        batch = updates[:50]
        stored = skipped = 0
        for item in batch:
            nid = str(item.get("node_id", "")).strip()
            s = str(item.get("summary", "")).strip()
            force = bool(item.get("force", False))
            if nid and s:
                r = await node_store.update_summary(db, nid, s, force=force)
                if r["updated"]:
                    stored += 1
                elif r["skipped"]:
                    skipped += 1
        return {"stored": stored, "skipped": skipped, "total": len(batch)}

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
            return {"ok": False, "error": "node not found"}
        if result["skipped"]:
            return {
                "ok": True,
                "skipped": True,
                "node_id": nid,
                "reason": "summary already cached and function unchanged",
            }
        return {"ok": True, "skipped": False, "node_id": nid}

    @mcp.tool()
    async def get_savings() -> dict:
        """Report tokens saved by Loom cache hits — all-time and recent.

        agent_hits: summaries written by you (store_understanding) — file reads provably skipped.
        auto_hits: structural summaries from analyze — may still need source for full context.
        """
        stats = await get_savings_stats(db)
        recent = await get_recent_savings(db, limit=10)
        return {
            **stats,
            "recent": recent,
            "note": "tokens_saved estimated from source line counts (15 tokens/line avg)",
        }

    @mcp.tool()
    async def get_context(node_id: str) -> dict | None:
        """Full context packet — everything to reason about a function without reading source.

        Returns summary, signature, callers (top 10), callees (top 10), and staleness flag.
        If summary_stale is True, check auto_summary for current metadata.
        For class/file nodes, returns members instead of callers/callees.

        Args:
            node_id: Exact node id from search_code results.
                     Example: 'function:src/auth.py:validate_token'
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        return await get_context_packet(db, nid)

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
        return result

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
            return {
                "error": "missing_args",
                "message": "Provide either previous_session_id or agent_id.",
            }

        session_row = None
        if previous_session_id:
            pid = _req_text(previous_session_id, field="previous_session_id", max_length=64)
            session_row = await get_session(db, pid)
            if session_row is None:
                return {
                    "error": "session_not_found",
                    "message": f"Session '{pid}' not found.",
                    "suggestion": "Use agent_id= to find your latest session instead.",
                }
        else:
            aid = _req_text(agent_id, field="agent_id", max_length=64)  # type: ignore[arg-type]
            session_row = await get_latest_session_for_agent(db, aid)
            if session_row is None:
                return {
                    "error": "no_prior_session",
                    "message": f"No previous session found for agent_id '{agent_id}'.",
                    "suggestion": "Call start_session() at the beginning of each session.",
                }

        return await get_delta_payload(db, since_ts=session_row["started_at"])

    @mcp.tool()
    async def get_surprising_connections(limit: int = 10) -> list[dict]:
        """Find non-obvious CALLS edges — cross-community, peripheral-to-hub, cross-module.

        Ranked by composite surprise score. Each result includes human-readable
        reasons explaining what makes it non-obvious.

        Useful for: discovering hidden coupling, unexpected dependencies,
        functions that act as unofficial bridges between subsystems.
        """
        return await _get_surprising_connections(db, limit=_clamp_limit(limit))

    @mcp.tool()
    async def suggest_questions(limit: int = 7) -> list[dict]:
        """Generate questions worth investigating based on graph topology.

        Question types:
        - dead_code: functions with no callers (unused or missing edges)
        - bridge_node: functions serving multiple communities (possible god function)
        - missing_summary: hot functions with no cached summary (high documentation value)
        - low_cohesion: communities whose members mostly call outside (refactor candidate)

        Call this at session start to prioritize what to investigate.
        """
        return await _suggest_questions(db, limit=_clamp_limit(limit))

    @mcp.tool()
    async def get_community_cohesion() -> list[dict]:
        """Cohesion score for every community.

        Cohesion = internal CALLS / (internal + external CALLS).
        1.0 = perfectly self-contained. 0.0 = all calls cross boundaries.

        Low cohesion (<0.2) communities are refactor candidates.
        """
        return await _get_community_cohesion(db)

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

    return mcp
