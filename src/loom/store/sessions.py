from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

from loom.core.context import DB


async def create_session(db: DB, *, agent_id: str = "default") -> dict[str, Any]:
    """Create a new session record.

    Args:
        db: Database context.
        agent_id: Identifier for agent type (e.g. 'claude-code', 'cursor').

    Returns:
        Dict with session_id, agent_id, started_at.
    """
    sid = str(uuid4())
    started_at = int(time.time())

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            conn.execute(
                "INSERT INTO sessions (id, agent_id, started_at) VALUES (?, ?, ?)",
                (sid, agent_id, started_at),
            )
            conn.commit()

    await asyncio.to_thread(_run)
    return {"session_id": sid, "agent_id": agent_id, "started_at": started_at}


async def get_session(db: DB, session_id: str) -> dict[str, Any] | None:
    """Fetch a session record by id.

    Args:
        db: Database context.
        session_id: UUID returned by create_session.

    Returns:
        Session dict or None if not found.
    """
    def _run() -> dict[str, Any] | None:
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT id, agent_id, started_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            return {"id": row["id"], "agent_id": row["agent_id"], "started_at": row["started_at"]}

    return await asyncio.to_thread(_run)


async def get_latest_session_for_agent(db: DB, agent_id: str) -> dict[str, Any] | None:
    """Find the most recent session for an agent.

    Args:
        db: Database context.
        agent_id: Agent identifier.

    Returns:
        Most recent session dict or None if no sessions exist.
    """
    def _run() -> dict[str, Any] | None:
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT id, agent_id, started_at FROM sessions "
                "WHERE agent_id = ? ORDER BY started_at DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if not row:
                return None
            return {"id": row["id"], "agent_id": row["agent_id"], "started_at": row["started_at"]}

    return await asyncio.to_thread(_run)


async def prune_sessions(db: DB, *, keep: int = 20) -> int:
    """Delete old sessions, keeping the most recent N per agent.

    Args:
        db: Database context.
        keep: Number of sessions to keep per agent_id.

    Returns:
        Number of sessions deleted.
    """
    def _run() -> int:
        with db._lock:
            conn = db.connect()
            agents = [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT agent_id FROM sessions"
                ).fetchall()
            ]
            deleted = 0
            for agent_id in agents:
                keep_ids = [
                    r[0] for r in conn.execute(
                        "SELECT id FROM sessions WHERE agent_id = ? "
                        "ORDER BY started_at DESC LIMIT ?",
                        (agent_id, keep),
                    ).fetchall()
                ]
                if not keep_ids:
                    continue
                ph = ",".join("?" * len(keep_ids))
                cur = conn.execute(
                    f"DELETE FROM sessions WHERE agent_id = ? AND id NOT IN ({ph})",
                    (agent_id, *keep_ids),
                )
                deleted += cur.rowcount
            conn.commit()
            return deleted

    return await asyncio.to_thread(_run)
