"""cohesion.py — community cohesion metrics.

Split from analysis/graph_insights.py.
"""
from __future__ import annotations

import asyncio

from loom.graph.db import DB
from loom.graph.models import EdgeType


async def get_community_cohesion(db: DB) -> list[dict]:
    """Return cohesion score for every community.

    Cohesion = internal CALLS / (internal CALLS + external CALLS).
    1.0 = perfectly self-contained. 0.0 = all calls cross boundaries.

    Returns:
        List of {community_id, name, size, cohesion, internal, external}.
    """

    def _run() -> list[dict]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """
                SELECT
                    c.id AS community_id,
                    c.name,
                    COALESCE(json_extract(c.metadata, '$.size'), 0) AS size,
                    COUNT(DISTINCT CASE
                        WHEN EXISTS (
                            SELECT 1 FROM nodes t
                            WHERE t.id = e.to_id AND t.community_id = c.id
                        ) THEN e.rowid END
                    ) AS internal_calls,
                    COUNT(DISTINCT CASE
                        WHEN NOT EXISTS (
                            SELECT 1 FROM nodes t
                            WHERE t.id = e.to_id AND t.community_id = c.id
                        ) THEN e.rowid END
                    ) AS external_calls
                FROM nodes c
                LEFT JOIN nodes member ON member.community_id = c.id
                    AND member.deleted_at IS NULL
                LEFT JOIN edges e ON e.from_id = member.id AND e.kind = ?
                WHERE c.kind = 'community'
                GROUP BY c.id
                ORDER BY size DESC
                """,
                (EdgeType.CALLS.value,),
            ).fetchall()

        result = []
        for row in rows:
            total = (row["internal_calls"] or 0) + (row["external_calls"] or 0)
            cohesion = (row["internal_calls"] or 0) / total if total > 0 else None
            result.append(
                {
                    "community_id": row["community_id"],
                    "name": row["name"],
                    "size": row["size"],
                    "cohesion": round(cohesion, 3) if cohesion is not None else None,
                    "internal_calls": row["internal_calls"] or 0,
                    "external_calls": row["external_calls"] or 0,
                }
            )
        return result

    return await asyncio.to_thread(_run)
