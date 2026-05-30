"""app.py — FastMCP server assembly."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore


def build_server(
    db_path: Path | None = None,
    *,
    db: object = None,
) -> object:
    """Build and return the FastMCP server with all tools registered."""
    from loom.graph.db import DB, resolve_db_path
    from loom.graph.db_pool import DBPool
    from loom.graph.projects import ProjectRegistry
    from loom.server import run as run_mod
    from loom.server.cache import MemoCache
    from loom.server.tools import analysis, context, graph, projects, search
    from loom.server.tools import session as session_tools

    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")

    registry = ProjectRegistry()
    pool = DBPool(registry)

    # Determine the current project's DB and prime the pool so the first call
    # has the same latency profile as v0.6.2 (no cold open on first tool call).
    if db is not None:
        pool.prime(db)  # type: ignore[arg-type]
        primary = db
    else:
        primary = DB(path=db_path or resolve_db_path())
        primary.connect()
        pool.prime(primary)  # type: ignore[arg-type]

    cache = MemoCache()
    session: dict[str, str] = {}

    search.register(mcp, pool, session, cache)
    graph.register(mcp, pool, session, cache)
    analysis.register(mcp, pool, session, cache)
    session_tools.register(mcp, pool, session, run_mod)
    context.register(mcp, pool, session, cache)
    projects.register(mcp, pool, session, cache)

    # Resources read from the primed (current) DB. They reflect the server's
    # boot project — they intentionally do NOT switch with `project=` args.
    primed = primary

    @mcp.resource("loom://savings")
    async def savings_resource() -> str:
        """Token savings report — how much Loom has saved across all sessions."""
        from loom.store.savings import get_recent_savings, get_savings_stats

        stats = await get_savings_stats(primed)
        recent = await get_recent_savings(primed, limit=5)
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
        """Compressed codebase overview — load at session start."""
        from loom.query.primer import build_primer

        result = await build_primer(primed)
        return str(result)

    @mcp.resource("loom://status")
    async def status_resource() -> str:
        """Live DB status — node count, indexing state, last analyzed."""
        import asyncio as _asyncio
        import time

        def _query() -> dict:
            with primed._lock:
                conn = primed.connect()
                node_count = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
                ).fetchone()[0]
                last_row = conn.execute(
                    "SELECT MAX(updated_at) AS ts FROM nodes WHERE deleted_at IS NULL"
                ).fetchone()
                last_ts = last_row["ts"] if last_row else None
            return {"node_count": node_count, "last_ts": last_ts}

        stats = await _asyncio.to_thread(_query)
        progress = run_mod._index_progress
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
            f"FTS5        : {'yes' if primed._fts5 else 'no'}",
            f"DB          : {primed.path}",
        ]
        if indexing:
            done = progress.get("files_processed", 0)
            total = progress.get("files_total", 0)
            lines.append(f"Progress    : {done}/{total} files ({progress.get('phase', '')})")
        return "\n".join(lines)

    return mcp
