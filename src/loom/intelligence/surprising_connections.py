"""surprising_connections.py — find non-obvious cross-boundary edges.

Split from analysis/graph_insights.py.
"""

from __future__ import annotations

import asyncio

from loom.graph.db import DB
from loom.graph.models import EdgeType


def _top_dir(path: str) -> str:
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


async def get_surprising_connections(db: DB, limit: int = 10) -> list[dict]:
    """Find CALLS edges that are non-obvious — cross-community, peripheral-to-hub, etc.

    Returns edges ranked by composite surprise score with human-readable reasons.
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
