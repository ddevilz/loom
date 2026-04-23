from __future__ import annotations

import asyncio

from loom.core.context import DB


async def mark_dead_code(db: DB) -> int:
    """Mark function/method nodes with zero incoming CALLS as is_dead_code=1.

    Returns count of nodes marked as dead code.
    """

    def _run() -> int:
        with db._lock:
            conn = db.connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("UPDATE nodes SET is_dead_code = 0")
                cur = conn.execute(
                    """UPDATE nodes SET is_dead_code = 1
                        WHERE kind IN ('function','method')
                          AND id NOT IN (
                              SELECT DISTINCT to_id FROM edges WHERE kind = 'calls'
                          )"""
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    return await asyncio.to_thread(_run)
