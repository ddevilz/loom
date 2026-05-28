from __future__ import annotations

import logging
import time
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
from loom.mcp.enums import Confidence, ConfidenceSignal, ErrorCode, WorkPlanPriority
from loom.query import traversal
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.context import get_context_packet
from loom.query.delta import get_delta_payload
from loom.query.primer import build_primer
from loom.query.search import find_replacement_candidates, search
from loom.store import nodes as node_store
from loom.store.node_visits import get_annotation_gaps, get_unannotated_reads, log_visit
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
    """Build and return the FastMCP server with all 21 tools registered."""
    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")
    if db is None:
        db = DB(path=db_path or DEFAULT_DB_PATH)

    # ── Session tracking ──────────────────────────────────────────────────────
    _session: dict[str, str] = {}  # holds {"id": session_id} when start_session called

    # ── In-process memo cache ─────────────────────────────────────────────────
    _MEMO_TTL = 300.0  # 5 min — matches Anthropic prompt-cache TTL
    _memo: dict[str, tuple[float, dict]] = {}  # key → (expires_at, result)

    def _mk(tool: str, node_id: str, **extra: object) -> str:
        key = f"{tool}:{node_id}"
        if extra:
            key += ":" + ":".join(f"{k}={v}" for k, v in sorted(extra.items()))
        return key

    def _memo_get(key: str) -> dict | None:
        entry = _memo.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        _memo.pop(key, None)
        return None

    def _memo_set(key: str, result: dict) -> None:
        _memo[key] = (time.monotonic() + _MEMO_TTL, result)

    def _memo_invalidate(node_id: str) -> None:
        needle_mid = f":{node_id}:"
        needle_end = f":{node_id}"
        for k in [k for k in _memo if needle_mid in k or k.endswith(needle_end)]:
            del _memo[k]

    def _is_test_path(path: str) -> bool:
        p = path.lower()
        return "/test" in p or p.startswith("test")

    def _compute_confidence(
        query: str,
        node_name: str,
        node_path: str,
        score: float,
        max_score: float,
        has_agent_summary: bool,
        caller_count: int,
    ) -> tuple[Confidence, list[ConfidenceSignal]]:
        signals: list[ConfidenceSignal] = []
        composite = 0.0
        if query.lower() == node_name.lower():
            composite += 0.40
            signals.append(ConfidenceSignal.EXACT_NAME_MATCH)
        norm_bm25 = (score / max_score) if max_score > 0 else 0.0
        composite += 0.25 * norm_bm25
        if norm_bm25 >= 0.7:
            signals.append(ConfidenceSignal.HIGH_BM25)
        if has_agent_summary:
            composite += 0.15
            signals.append(ConfidenceSignal.HAS_AGENT_SUMMARY)
        if caller_count > 5:
            composite += 0.12
            signals.append(ConfidenceSignal.HOT_NODE)
        if query.lower() in node_path.lower():
            composite += 0.08
            signals.append(ConfidenceSignal.PATH_MATCH)
        if composite >= 0.65:
            return Confidence.HIGH, signals
        if composite >= 0.35:
            return Confidence.MEDIUM, signals
        return Confidence.LOW, signals

    async def _log(node_id: str, tool: str) -> None:
        sid = _session.get("id")
        if sid:
            await log_visit(db, session_id=sid, node_id=node_id, tool=tool)

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> dict:
        """Search nodes by name/summary/path via FTS5 or LIKE.

        Results include caller_count, community_id, and is_dead_code for disambiguation.
        Dead nodes are ranked last with replacement_candidates where detectable.
        Test-file nodes are deprioritised (score penalty applied).
        Nodes that are dead but have a live replacement are injected with suggested_instead=true.
        """
        q = _req_text(query, field="query", max_length=_MAX_QUERY)
        raw = await search(q, db, limit=_clamp_limit(limit))

        # Apply test-path score penalty
        for r in raw:
            if _is_test_path(r.node.path):
                r.score *= 0.3

        live = sorted(
            [r for r in raw if not r.node.is_dead_code],
            key=lambda r: r.score,
            reverse=True,
        )
        dead = sorted(
            [r for r in raw if r.node.is_dead_code],
            key=lambda r: r.caller_count,
            reverse=True,
        )

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

            confidence, signals = _compute_confidence(
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
                "is_dead_code": node.is_dead_code,
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
                # Inject top replacement as a suggested_instead entry if not already present
                top = candidates[0]
                if top.id not in seen_ids:
                    seen_ids.add(top.id)
                    # Build a lightweight suggested entry without a full SearchResult
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

        return _ok(output)

    @mcp.tool()
    async def get_node(node_id: str) -> dict:
        """Return a single node by id."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        n = await node_store.get_node(db, nid)
        return _ok(
            None
            if n is None
            else {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "kind": n.kind.value,
                "language": n.language,
                "summary": n.summary,
                "start_line": n.start_line,
                "end_line": n.end_line,
            }
        )

    @mcp.tool()
    async def get_callers(
        node_id: str,
        limit: int = 10,
        include_summaries: bool = True,
    ) -> dict:
        """One-hop incoming CALLS — functions that call this node.

        Args:
            limit: Max callers to return (1-100). Default 10.
            include_summaries: Include summary text. Set False for names/paths only (~70% smaller).
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        await _log(nid, "get_callers")
        key = _mk("get_callers", nid)
        if (hit := _memo_get(key)) is not None:
            return hit
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="in"
        )
        nodes = nodes[: _clamp_limit(limit)]
        if include_summaries:
            result = _ok(
                [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes]
            )
        else:
            result = _ok([{"id": n.id, "name": n.name, "path": n.path} for n in nodes])
        _memo_set(key, result)
        return result

    @mcp.tool()
    async def get_callees(
        node_id: str,
        limit: int = 10,
        include_summaries: bool = True,
    ) -> dict:
        """One-hop outgoing CALLS — functions this node calls.

        Args:
            limit: Max callees to return (1-100). Default 10.
            include_summaries: Include summary text. Set False for names/paths only (~70% smaller).
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        await _log(nid, "get_callees")
        key = _mk("get_callees", nid)
        if (hit := _memo_get(key)) is not None:
            return hit
        nodes = await traversal.neighbors(
            db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="out"
        )
        nodes = nodes[: _clamp_limit(limit)]
        if include_summaries:
            result = _ok(
                [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in nodes]
            )
        else:
            result = _ok([{"id": n.id, "name": n.name, "path": n.path} for n in nodes])
        _memo_set(key, result)
        return result

    @mcp.tool()
    async def get_blast_radius(
        node_id: str, depth: int = 3, limit: int = 50, offset: int = 0
    ) -> dict:
        """Transitive callers via SQLite recursive CTE. Paginated."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        await _log(nid, "get_blast_radius")
        d = _clamp_depth(depth)
        lim = max(1, min(limit, 200))
        key = _mk("get_blast_radius", nid, depth=d, limit=lim, offset=offset)
        if (hit := _memo_get(key)) is not None:
            return hit
        result = _ok(
            await build_blast_radius_payload(db, node_id=nid, depth=d, limit=lim, offset=offset)
        )
        _memo_set(key, result)
        return result

    @mcp.tool()
    async def get_neighbors(
        node_id: str,
        depth: int = 1,
        limit: int = 20,
        include_summaries: bool = True,
    ) -> dict:
        """Generic neighbor traversal across all edge kinds, both directions.

        Args:
            depth: Hop depth (1-10). Default 1.
            limit: Max neighbors to return (1-100). Default 20.
            include_summaries: Include summary text. Set False for names/paths only.
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        await _log(nid, "get_neighbors")
        d = _clamp_depth(depth)
        lim = _clamp_limit(limit)
        key = _mk("get_neighbors", nid, depth=d, limit=lim)
        if (hit := _memo_get(key)) is not None:
            return hit
        nodes = await traversal.neighbors(db, nid, depth=d)
        nodes = nodes[:lim]
        if include_summaries:
            result = _ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "kind": n.kind.value,
                        "summary": n.summary,
                    }
                    for n in nodes
                ]
            )
        else:
            result = _ok(
                [{"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value} for n in nodes]
            )
        _memo_set(key, result)
        return result

    @mcp.tool()
    async def get_community(
        community_id: str,
        limit: int = 50,
        include_summaries: bool = True,
    ) -> dict:
        """Return member nodes of a community cluster.

        Args:
            limit: Max members to return (1-100). Default 50.
            include_summaries: Include summary text. Set False for names/paths only.
        """
        cid = _req_text(community_id, field="community_id", max_length=_MAX_ID)
        nodes = await traversal.community_members(db, cid)
        nodes = nodes[: _clamp_limit(limit)]
        if include_summaries:
            return _ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "kind": n.kind.value,
                        "summary": n.summary,
                    }
                    for n in nodes
                ]
            )
        return _ok(
            [{"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value} for n in nodes]
        )

    @mcp.tool()
    async def shortest_path(
        from_id: str,
        to_id: str,
        include_summaries: bool = True,
    ) -> dict:
        """Shortest directed path on CALLS subgraph.

        Args:
            include_summaries: Include summary text on path nodes. Set False for names/paths only.
        """
        fid = _req_text(from_id, field="from_id", max_length=_MAX_ID)
        tid = _req_text(to_id, field="to_id", max_length=_MAX_ID)
        path = await traversal.shortest_path(db, fid, tid)
        if path is None:
            return _ok(None)
        if include_summaries:
            return _ok(
                [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in path]
            )
        return _ok([{"id": n.id, "name": n.name, "path": n.path} for n in path])

    @mcp.tool()
    async def graph_stats() -> dict:
        """Node/edge counts broken down by kind."""
        return _ok(await traversal.stats(db))

    @mcp.tool()
    async def god_nodes(limit: int = 20, include_summaries: bool = True) -> dict:
        """Highest in-degree on CALLS subgraph (most-called functions).

        Args:
            limit: Max nodes to return (1-100). Default 20.
            include_summaries: Include summary text. Set False for names/paths/degree only.
        """
        pairs = await traversal.god_nodes(db, _clamp_limit(limit))
        if include_summaries:
            return _ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "in_degree": deg,
                        "summary": n.summary,
                    }
                    for n, deg in pairs
                ]
            )
        return _ok(
            [{"id": n.id, "name": n.name, "path": n.path, "in_degree": deg} for n, deg in pairs]
        )

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
                author=_session.get("agent_id"),
                session_id=_session.get("id"),
            )
            if not r["found"]:
                errors.append({"node_id": nid, "error_code": ErrorCode.NODE_NOT_FOUND})
            elif r["updated"]:
                _memo_invalidate(nid)
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
        result = await node_store.update_summary(
            db,
            nid,
            s,
            force=force,
            author=_session.get("agent_id"),
            session_id=_session.get("id"),
        )
        if not result["found"]:
            return _err(
                ErrorCode.NODE_NOT_FOUND,
                f"Node '{nid}' not found.",
                "Use search_code() to find the correct ID.",
            )
        if result["updated"]:
            _memo_invalidate(nid)
        return _ok({"skipped": result["skipped"], "node_id": nid})

    @mcp.tool()
    async def get_savings() -> dict:
        """Report tokens saved by Loom cache hits — all-time and recent.

        agent_hits: summaries written by you (store_understanding) — file reads provably skipped.
        auto_hits: structural summaries from analyze — may still need source for full context.
        """
        stats = await get_savings_stats(db)
        recent = await get_recent_savings(db, limit=10)
        return _ok({**stats, "recent": recent})

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
        await _log(nid, "get_context")
        key = _mk("get_context", nid)
        if (hit := _memo_get(key)) is not None:
            return hit
        packet = await get_context_packet(db, nid)
        if packet and packet.get("summary_source") == SummarySource.AUTO:
            packet["_nudge"] = (
                f"No agent understanding stored for '{nid}'. "
                f"After reading, call store_understanding(node_id='{nid}', "
                f"summary='your interpretation')."
            )
        result = _ok(packet)
        _memo_set(key, result)
        return result

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
        aid = _req_text(agent_id, field="agent_id", max_length=64)

        # Fetch previous session before creating the new one
        prev = await get_latest_session_for_agent(db, aid)

        result = await create_session(db, agent_id=aid)
        _session["id"] = result["session_id"]
        _session["agent_id"] = aid

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

        import asyncio as _asyncio

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

        return _ok(
            {
                "priority": priority,
                "reason": reason,
                "summary_coverage": coverage,
                "tasks": tasks,
                "session_id": _session.get("id"),
            }
        )

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
