"""suggested_questions.py — topology-driven agent investigation questions.

Split from analysis/graph_insights.py.
"""

from __future__ import annotations

import asyncio

from loom.graph.db import DB
from loom.graph.models import EdgeType, QuestionType


async def suggest_questions(db: DB, limit: int = 7) -> list[dict]:
    """Generate questions an agent should investigate based on graph topology.

    Question types:
    - dead_code: functions with no callers (possibly unused)
    - bridge_node: functions called from multiple communities (cross-cutting)
    - missing_summary: hot functions with no summary (high documentation value)
    - low_cohesion: communities with many external calls vs internal

    Returns list of {type, question, node_id, why}.
    """
    limit = max(1, min(limit, 20))

    def _run() -> list[dict]:
        with db._lock:
            conn = db.connect()
            questions: list[dict] = []

            # 1. Dead code — functions with no callers
            orphans = conn.execute(
                """
                SELECT n.id, n.name, n.path
                FROM nodes n
                WHERE n.kind IN ('function', 'method')
                  AND n.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM edges e
                      WHERE e.to_id = n.id AND e.kind = ?
                  )
                ORDER BY n.name
                LIMIT 5
                """,
                (EdgeType.CALLS.value,),
            ).fetchall()
            if orphans:
                names = ", ".join(f"`{r['name']}`" for r in orphans[:3])
                extra = len(orphans) - 3
                suffix = f" (and {extra} more)" if extra > 0 else ""
                questions.append(
                    {
                        "type": QuestionType.DEAD_CODE,
                        "question": (
                            f"Are {names}{suffix} actually"
                            " unused, or are callers missing from the index?"
                        ),
                        "node_id": orphans[0]["id"],
                        "why": (
                            f"{len(orphans)} functions have no incoming CALLS edges"
                            " — potential dead code or indexing gap."
                        ),
                    }
                )

            # 2. Bridge nodes — called from multiple distinct communities
            bridges = conn.execute(
                """
                SELECT
                    n.id, n.name, n.path,
                    COUNT(DISTINCT caller.community_id) AS comm_count,
                    GROUP_CONCAT(DISTINCT caller.community_id) AS comms
                FROM nodes n
                JOIN edges e ON e.to_id = n.id AND e.kind = ?
                JOIN nodes caller ON caller.id = e.from_id
                WHERE n.deleted_at IS NULL
                  AND n.kind IN ('function', 'method')
                  AND caller.community_id IS NOT NULL
                  AND caller.community_id != n.community_id
                GROUP BY n.id
                HAVING comm_count >= 3
                ORDER BY comm_count DESC
                LIMIT 3
                """,
                (EdgeType.CALLS.value,),
            ).fetchall()
            for row in bridges:
                questions.append(
                    {
                        "type": QuestionType.BRIDGE_NODE,
                        "question": (
                            f"Why does `{row['name']}` serve as a cross-cutting"
                            f" dependency across {row['comm_count']} separate communities?"
                        ),
                        "node_id": row["id"],
                        "why": (
                            f"Called from {row['comm_count']} different communities"
                            " — possible god function or missing abstraction layer."
                        ),
                    }
                )

            # 3. Hot functions with no summary — highest documentation value
            undocumented = conn.execute(
                """
                SELECT n.id, n.name, n.path,
                       COUNT(e.from_id) AS caller_count
                FROM nodes n
                JOIN edges e ON e.to_id = n.id AND e.kind = ?
                WHERE n.kind IN ('function', 'method')
                  AND n.deleted_at IS NULL
                  AND (n.summary IS NULL OR n.summary = '')
                GROUP BY n.id
                ORDER BY caller_count DESC
                LIMIT 3
                """,
                (EdgeType.CALLS.value,),
            ).fetchall()
            for row in undocumented:
                questions.append(
                    {
                        "type": QuestionType.MISSING_SUMMARY,
                        "question": (
                            f"What does `{row['name']}` do and why does it exist?"
                            f" ({row['caller_count']} callers, no summary)"
                        ),
                        "node_id": row["id"],
                        "why": (
                            f"Called {row['caller_count']} times but has no agent summary."
                            " High-value target for store_understanding."
                        ),
                    }
                )

            # 4. Low-cohesion communities — many external calls, few internal
            low_cohesion = conn.execute(
                """
                SELECT
                    c.id AS community_id,
                    c.name,
                    COUNT(DISTINCT internal_e.from_id) AS internal_calls,
                    COUNT(DISTINCT external_e.from_id) AS external_calls,
                    json_extract(c.metadata, '$.size') AS size
                FROM nodes c
                LEFT JOIN nodes member ON member.community_id = c.id
                    AND member.deleted_at IS NULL
                LEFT JOIN edges internal_e ON internal_e.from_id = member.id
                    AND internal_e.kind = ?
                    AND EXISTS (
                        SELECT 1 FROM nodes t
                        WHERE t.id = internal_e.to_id
                          AND t.community_id = c.id
                    )
                LEFT JOIN edges external_e ON external_e.from_id = member.id
                    AND external_e.kind = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM nodes t
                        WHERE t.id = external_e.to_id
                          AND t.community_id = c.id
                    )
                WHERE c.kind = 'community'
                GROUP BY c.id
                HAVING size >= 5
                   AND (internal_calls + external_calls) > 0
                   AND CAST(internal_calls AS REAL) / (internal_calls + external_calls) < 0.2
                ORDER BY CAST(internal_calls AS REAL) / (internal_calls + external_calls) ASC
                LIMIT 2
                """,
                (EdgeType.CALLS.value, EdgeType.CALLS.value),
            ).fetchall()
            for row in low_cohesion:
                total = (row["internal_calls"] or 0) + (row["external_calls"] or 0)
                cohesion = (row["internal_calls"] or 0) / total if total else 0
                questions.append(
                    {
                        "type": QuestionType.LOW_COHESION,
                        "question": (
                            f"Should the `{row['name']}` cluster be split?"
                            f" Only {cohesion:.0%} of its calls are internal."
                        ),
                        "node_id": row["community_id"],
                        "why": (
                            f"Community cohesion {cohesion:.2f} — nodes loosely related."
                            " Consider refactoring into tighter modules."
                        ),
                    }
                )

            return questions[:limit]

    return await asyncio.to_thread(_run)
