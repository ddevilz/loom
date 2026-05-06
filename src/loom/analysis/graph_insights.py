"""Graph topology insights — surprising connections, suggested questions, community cohesion.

Inspired by graphify's analyze.py; adapted for Loom's SQLite graph.
All queries are pure SQL — no extra dependencies.
"""

from __future__ import annotations

import asyncio

from loom.core.context import DB
from loom.core.edge import EdgeType
from loom.core.enums import QuestionType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _top_dir(path: str) -> str:
    """First path component — used to detect cross-module calls."""
    parts = path.replace("\\", "/").split("/")
    return parts[0] if parts else path


def _surprise_score(
    caller_path: str,
    callee_path: str,
    caller_in: int,
    caller_out: int,
    callee_in: int,
    callee_out: int,
    cross_community: bool,
    confidence: float,
) -> tuple[int, list[str]]:
    """Composite surprise score. Higher = more non-obvious."""
    score = 0
    reasons: list[str] = []

    if cross_community:
        score += 2
        reasons.append("bridges separate communities")

    if _top_dir(caller_path) != _top_dir(callee_path):
        score += 2
        reasons.append("connects across modules")

    caller_degree = caller_in + caller_out
    callee_degree = callee_in + callee_out
    if caller_degree <= 2 and callee_degree >= 10:
        score += 2
        reasons.append(f"peripheral caller reaches hub ({callee_degree} connections)")

    if confidence < 0.7:
        score += 1
        reasons.append(f"low confidence ({confidence:.2f})")

    caller_subdir = "/".join(caller_path.replace("\\", "/").split("/")[:2])
    callee_subdir = "/".join(callee_path.replace("\\", "/").split("/")[:2])
    if caller_subdir != callee_subdir and caller_path and callee_path:
        score += 1
        reasons.append("different subdirectory")

    return score, reasons


# ---------------------------------------------------------------------------
# get_surprising_connections
# ---------------------------------------------------------------------------


async def get_surprising_connections(db: DB, limit: int = 10) -> list[dict]:
    """Find CALLS edges that are non-obvious — cross-community, peripheral-to-hub, etc.

    Returns edges ranked by composite surprise score with human-readable reasons.

    Args:
        db: Loom database.
        limit: Max results. Capped at 50.

    Returns:
        List of {caller, callee, caller_path, callee_path, score, reasons}.
    """
    limit = max(1, min(limit, 50))

    def _run() -> list[dict]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """
                SELECT
                    e.from_id, e.to_id,
                    COALESCE(e.confidence, 1.0) AS confidence,
                    n1.name    AS caller_name,
                    n1.path    AS caller_path,
                    n1.summary AS caller_summary,
                    n1.community_id AS caller_comm,
                    n2.name    AS callee_name,
                    n2.path    AS callee_path,
                    n2.summary AS callee_summary,
                    n2.community_id AS callee_comm,
                    (SELECT COUNT(*) FROM edges
                     WHERE to_id = e.from_id AND kind = ?) AS caller_in,
                    (SELECT COUNT(*) FROM edges
                     WHERE from_id = e.from_id AND kind = ?) AS caller_out,
                    (SELECT COUNT(*) FROM edges
                     WHERE to_id = e.to_id AND kind = ?) AS callee_in,
                    (SELECT COUNT(*) FROM edges
                     WHERE from_id = e.to_id AND kind = ?) AS callee_out
                FROM edges e
                JOIN nodes n1 ON n1.id = e.from_id
                JOIN nodes n2 ON n2.id = e.to_id
                WHERE e.kind = ?
                  AND n1.deleted_at IS NULL
                  AND n2.deleted_at IS NULL
                  AND n1.kind NOT IN ('file', 'community')
                  AND n2.kind NOT IN ('file', 'community')
                  AND n1.path != n2.path
                LIMIT 2000
                """,
                (
                    EdgeType.CALLS.value,
                    EdgeType.CALLS.value,
                    EdgeType.CALLS.value,
                    EdgeType.CALLS.value,
                    EdgeType.CALLS.value,
                ),
            ).fetchall()

        candidates = []
        for row in rows:
            cross_comm = (
                row["caller_comm"] is not None
                and row["callee_comm"] is not None
                and row["caller_comm"] != row["callee_comm"]
            )
            score, reasons = _surprise_score(
                caller_path=row["caller_path"] or "",
                callee_path=row["callee_path"] or "",
                caller_in=row["caller_in"],
                caller_out=row["caller_out"],
                callee_in=row["callee_in"],
                callee_out=row["callee_out"],
                cross_community=cross_comm,
                confidence=row["confidence"],
            )
            if score == 0:
                continue
            candidates.append(
                {
                    "_score": score,
                    "caller": row["caller_name"],
                    "caller_id": row["from_id"],
                    "caller_path": row["caller_path"],
                    "caller_summary": row["caller_summary"],
                    "callee": row["callee_name"],
                    "callee_id": row["to_id"],
                    "callee_path": row["callee_path"],
                    "callee_summary": row["callee_summary"],
                    "score": score,
                    "reasons": reasons,
                    "cross_community": cross_comm,
                }
            )

        candidates.sort(key=lambda x: x["_score"], reverse=True)
        for c in candidates:
            c.pop("_score")

        # Deduplicate by community pair — one representative per boundary
        seen_pairs: set[tuple[str, str]] = set()
        deduped: list[dict] = []
        for c in candidates:
            if c["cross_community"]:
                caller_id = c["caller_id"]
                callee_id = c["callee_id"]
                pair = (min(caller_id, callee_id), max(caller_id, callee_id))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
            deduped.append(c)
            if len(deduped) >= limit:
                break

        return deduped

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# suggest_questions
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# community_cohesion
# ---------------------------------------------------------------------------


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
