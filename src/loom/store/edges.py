from __future__ import annotations

import asyncio
import json

from loom.core.context import DB
from loom.core.edge import Edge


async def bulk_upsert_edges(db: DB, edges: list[Edge]) -> None:
    if not edges:
        return

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            rows = [
                (
                    e.from_id, e.to_id, e.kind.value, e.confidence,
                    e.confidence_tier.value, json.dumps(e.metadata, default=str),
                )
                for e in edges
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO edges
                     (from_id, to_id, kind, confidence, confidence_tier, metadata)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )
            conn.commit()

    await asyncio.to_thread(_run)
