from __future__ import annotations

import asyncio
import time
from typing import Any

from loom.core.context import DB


async def log_visit(db: DB, *, session_id: str, node_id: str, tool: str) -> None:
    """Record that an agent read node_id during session_id via tool."""
    ts = int(time.time())

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            conn.execute(
                "INSERT INTO node_visits (session_id, node_id, tool, visited_at) VALUES (?,?,?,?)",
                (session_id, node_id, tool, ts),
            )
            conn.commit()

    await asyncio.to_thread(_run)


async def get_unannotated_reads(db: DB, session_id: str) -> list[dict[str, Any]]:
    """Nodes read in session_id that have no AGENT summary or a stale one.

    A summary is stale when summary_hash != content_hash (code changed since written).
    Returns rows ordered by last visit time descending.
    """

    def _run() -> list[dict[str, Any]]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """SELECT nv.node_id, n.name, n.path, n.kind,
                          MAX(nv.visited_at) AS last_visited,
                          MAX(nv.tool) AS last_tool,
                          n.summary_hash,
                          n.content_hash
                     FROM node_visits nv
                     JOIN nodes n ON n.id = nv.node_id
                    WHERE nv.session_id = ?
                      AND n.deleted_at IS NULL
                      AND (
                            n.summary_hash IS NULL
                            OR (n.content_hash IS NOT NULL AND n.summary_hash != n.content_hash)
                          )
                    GROUP BY nv.node_id
                    ORDER BY last_visited DESC""",
                (session_id,),
            ).fetchall()
            return [
                {
                    "node_id": r["node_id"],
                    "name": r["name"],
                    "path": r["path"],
                    "kind": r["kind"],
                    "last_visited": r["last_visited"],
                    "last_tool": r["last_tool"],
                    "stale": r["summary_hash"] is not None,  # has summary but it's stale
                }
                for r in rows
            ]

    return await asyncio.to_thread(_run)


async def get_annotation_gaps(db: DB, *, limit: int = 5) -> list[dict[str, Any]]:
    """Top nodes by visit count across ALL sessions that still have no AGENT summary.

    High visit count = agent keeps re-reading without retaining understanding.
    These are the highest-value annotation targets.
    """

    def _run() -> list[dict[str, Any]]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """SELECT nv.node_id, n.name, n.path, n.kind, COUNT(*) AS visit_count
                     FROM node_visits nv
                     JOIN nodes n ON n.id = nv.node_id
                    WHERE n.deleted_at IS NULL
                      AND (
                            n.summary_hash IS NULL
                            OR (n.content_hash IS NOT NULL AND n.summary_hash != n.content_hash)
                          )
                    GROUP BY nv.node_id
                    ORDER BY visit_count DESC
                    LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                {
                    "node_id": r["node_id"],
                    "name": r["name"],
                    "path": r["path"],
                    "kind": r["kind"],
                    "visit_count": r["visit_count"],
                }
                for r in rows
            ]

    return await asyncio.to_thread(_run)


async def prune_orphaned_visits(db: DB) -> int:
    """Delete visits whose session no longer exists. Call after prune_sessions."""

    def _run() -> int:
        with db._lock:
            conn = db.connect()
            cur = conn.execute(
                "DELETE FROM node_visits WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            conn.commit()
            return cur.rowcount

    return await asyncio.to_thread(_run)
