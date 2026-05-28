"""AnalyticsRepository — synchronous savings/cache-hit persistence layer.

Extracted from src/loom/store/savings.py (async), converted to pure synchronous
methods.
"""
from __future__ import annotations

import time

from loom.graph.db import DB

_META_TOTAL_TOKENS = "savings_total_tokens"
_META_TOTAL_HITS = "savings_total_hits"
_META_AGENT_HITS = "savings_agent_hits"
_META_AUTO_HITS = "savings_auto_hits"


class AnalyticsRepository:
    """Synchronous operations for savings and meta counters tables."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def log_saving(
        self,
        node_id: str,
        query: str | None,
        tokens_saved: int,
        summary_type: str,
    ) -> None:
        """Record a cache hit and update cumulative counters in meta.

        Args:
            node_id: Node whose summary was returned (file read skipped).
            query: Search query that triggered the hit.
            tokens_saved: Estimated tokens saved (source lines × 15 minus summary tokens).
            summary_type: 'agent' if human-verified summary, 'auto' if metadata-generated.
        """
        if tokens_saved <= 0:
            return

        with self._db._lock:
            conn = self._db.connect()
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

    def get_stats(self) -> dict:
        """Return cumulative savings counters from meta table.

        Returns:
            Dict with total_tokens_saved, total_hits, agent_hits, auto_hits.
        """
        with self._db._lock:
            conn = self._db.connect()
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

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Return most recent cache hit events.

        Args:
            limit: Max rows to return.

        Returns:
            List of {ts, node_id, query, tokens_saved, summary_type} dicts.
        """
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT ts, node_id, query, tokens_saved, summary_type "
                "FROM savings ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
