from __future__ import annotations

import asyncio
import json

from loom.graph.db import DB

# Name suffixes that suggest a node is intentionally superseded
_LEGACY_SUFFIXES = ("_old", "_legacy", "_deprecated", "_v1", "_v2_old", "_bak", "_backup")
# Keywords in summary/docstring that signal deprecation
_DEPRECATION_KEYWORDS = (
    "deprecated",
    "use instead",
    "replaced by",
    "use ",
    "do not use",
    "obsolete",
)


def _infer_dead_reason(name: str, summary: str | None) -> str:
    """Heuristic: infer why a node has no callers."""
    name_lower = name.lower()
    if any(name_lower.endswith(s) for s in _LEGACY_SUFFIXES):
        return "name suggests legacy/superseded version"
    if summary:
        sl = summary.lower()
        for kw in _DEPRECATION_KEYWORDS:
            if kw in sl:
                return f"summary contains deprecation hint: '{kw}'"
    return "no callers"


async def mark_dead_code(db: DB) -> int:
    """Mark function/method nodes with zero incoming CALLS with "dead-code" tag.

    Also enriches each dead node's metadata with:
      - dead_reason: heuristic explanation (name pattern, docstring hint, or "no callers")
      - replacement_candidates: up to 3 same-file live siblings with callers

    Returns count of nodes marked as dead code.
    """

    def _run() -> int:
        with db._lock:
            conn = db.connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Clear existing dead-code tags
                conn.execute("DELETE FROM node_tags WHERE tag = 'dead-code' AND source = 'system'")
                # Find dead nodes: function/method with zero incoming CALLS
                dead_rows_cur = conn.execute(
                    """SELECT id, name, path, summary, metadata FROM nodes
                        WHERE kind IN ('function','method')
                          AND deleted_at IS NULL
                          AND id NOT IN (
                              SELECT DISTINCT to_id FROM edges WHERE kind = 'CALLS'
                          )"""
                )
                dead_rows = dead_rows_cur.fetchall()
                dead_count = len(dead_rows)

                if dead_count == 0:
                    conn.commit()
                    return 0

                # Tag dead nodes
                conn.executemany(
                    "INSERT OR IGNORE INTO node_tags (node_id, tag, source) VALUES (?, 'dead-code', 'system')",
                    [(row["id"],) for row in dead_rows],
                )

                for row in dead_rows:
                    node_id = row["id"]
                    name = row["name"]
                    path = row["path"]
                    summary = row["summary"]
                    metadata: dict = json.loads(row["metadata"]) if row["metadata"] else {}

                    dead_reason = _infer_dead_reason(name, summary)

                    # Same-file live siblings with callers
                    candidates = conn.execute(
                        """SELECT n.id, n.name, n.path,
                                  (SELECT COUNT(*) FROM edges
                                   WHERE to_id = n.id AND kind = 'CALLS') AS caller_count
                             FROM nodes n
                            WHERE n.path = ?
                              AND n.kind IN ('function', 'method')
                              AND n.deleted_at IS NULL
                              AND n.id != ?
                              AND (SELECT COUNT(*) FROM edges
                                   WHERE to_id = n.id AND kind = 'CALLS') > 0
                            ORDER BY caller_count DESC
                            LIMIT 3""",
                        (path, node_id),
                    ).fetchall()

                    metadata["dead_reason"] = dead_reason
                    metadata["replacement_candidates"] = [
                        {
                            "id": c["id"],
                            "name": c["name"],
                            "path": c["path"],
                            "caller_count": c["caller_count"],
                        }
                        for c in candidates
                    ]

                    conn.execute(
                        "UPDATE nodes SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata), node_id),
                    )

                conn.commit()
                return dead_count
            except Exception:
                conn.rollback()
                raise

    return await asyncio.to_thread(_run)
