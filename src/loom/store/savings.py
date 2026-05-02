from __future__ import annotations

import asyncio
import time

from loom.core.context import DB

_META_TOTAL_TOKENS = "savings_total_tokens"
_META_TOTAL_HITS = "savings_total_hits"
_META_AGENT_HITS = "savings_agent_hits"
_META_AUTO_HITS = "savings_auto_hits"


async def log_saving(
    db: DB,
    *,
    node_id: str,
    query: str | None,
    tokens_saved: int,
    summary_type: str,
) -> None:
    """Record a cache hit and update cumulative counters in meta.

    Args:
        db: Database context.
        node_id: Node whose summary was returned (file read skipped).
        query: Search query that triggered the hit.
        tokens_saved: Estimated tokens saved (source lines × 15 minus summary tokens).
        summary_type: 'agent' if human-verified summary, 'auto' if metadata-generated.
    """
    if tokens_saved <= 0:
        return

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            now = int(time.time())
            conn.execute(
                "INSERT INTO savings (ts, node_id, query, tokens_saved, summary_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (now, node_id, query, tokens_saved, summary_type),
            )
            # Update meta counters (upsert pattern)
            for key, delta in [
                (_META_TOTAL_TOKENS, tokens_saved),
                (_META_TOTAL_HITS, 1),
                (_META_AGENT_HITS if summary_type == "agent" else _META_AUTO_HITS, 1),
            ]:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = CAST(CAST(value AS INTEGER) + ? AS TEXT)",
                    (key, str(delta), delta),
                )
            conn.commit()

    await asyncio.to_thread(_run)


async def get_savings_stats(db: DB) -> dict:
    """Return cumulative savings counters from meta table.

    Returns:
        Dict with total_tokens_saved, total_hits, agent_hits, auto_hits.
    """

    def _run() -> dict:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT key, value FROM meta WHERE key IN (?, ?, ?, ?)",
                (_META_TOTAL_TOKENS, _META_TOTAL_HITS, _META_AGENT_HITS, _META_AUTO_HITS),
            ).fetchall()
            meta = {r["key"]: int(r["value"]) for r in rows}
            return {
                "total_tokens_saved": meta.get(_META_TOTAL_TOKENS, 0),
                "total_hits": meta.get(_META_TOTAL_HITS, 0),
                "agent_hits": meta.get(_META_AGENT_HITS, 0),
                "auto_hits": meta.get(_META_AUTO_HITS, 0),
            }

    return await asyncio.to_thread(_run)


async def get_recent_savings(db: DB, limit: int = 20) -> list[dict]:
    """Return most recent cache hit events.

    Args:
        db: Database context.
        limit: Max rows to return.

    Returns:
        List of {ts, node_id, query, tokens_saved, summary_type} dicts.
    """

    def _run() -> list[dict]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT ts, node_id, query, tokens_saved, summary_type "
                "FROM savings ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    return await asyncio.to_thread(_run)
