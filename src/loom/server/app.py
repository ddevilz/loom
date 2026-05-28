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
    """Build and return the FastMCP server with all 17 tools registered."""
    from loom.graph.db import DB, DEFAULT_DB_PATH
    from loom.server import run as run_mod
    from loom.server.cache import MemoCache
    from loom.server.tools import analysis, context, graph, search
    from loom.server.tools import session as session_tools

    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")
    if db is None:
        db = DB(path=db_path or DEFAULT_DB_PATH)

    cache = MemoCache()
    session: dict[str, str] = {}

    search.register(mcp, db, session, cache)
    graph.register(mcp, db, session, cache)
    analysis.register(mcp, db, session, cache)
    session_tools.register(mcp, db, session, run_mod)
    context.register(mcp, db, session, cache)

    # ── Resources ─────────────────────────────────────────────────────────────

    @mcp.resource("loom://savings")
    async def savings_resource() -> str:
        """Token savings report — how much Loom has saved across all sessions."""
        from loom.store.savings import get_recent_savings, get_savings_stats

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
        from loom.query.primer import build_primer

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
            f"FTS5        : {'yes' if db._fts5 else 'no'}",
            f"DB          : {db.path}",
        ]
        if indexing:
            done = progress.get("files_processed", 0)
            total = progress.get("files_total", 0)
            lines.append(f"Progress    : {done}/{total} files ({progress.get('phase', '')})")
        return "\n".join(lines)

    return mcp
