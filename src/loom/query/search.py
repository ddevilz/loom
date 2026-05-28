from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass

from loom.graph.db import DB
from loom.graph.models import Node
from loom.store.nodes import row_to_node


@dataclass
class SearchResult:
    node: Node
    score: float
    caller_count: int = 0


@dataclass
class ReplacementCandidate:
    id: str
    name: str
    path: str
    caller_count: int


async def search(query: str, db: DB, *, limit: int = 10) -> list[SearchResult]:
    """Search for nodes by name prefix or FTS5 full-text.

    Args:
        query: Search string. For FTS5 this is a full-text query; for LIKE fallback
               it matches against node names.
        db: Database context.
        limit: Maximum number of results to return.

    Returns:
        List of SearchResult ordered by relevance (highest score first).
        Soft-deleted nodes are excluded. caller_count included for ranking.
    """

    def _run() -> list[tuple[Node, float, int]]:
        with db._lock:
            conn = db.connect()
            if db._fts5:
                try:
                    rows = conn.execute(
                        """SELECT n.*, -bm25(nodes_fts) AS _score,
                                  (SELECT COUNT(*) FROM edges
                                   WHERE to_id = n.id AND kind = 'calls') AS _caller_count
                             FROM nodes_fts
                             JOIN nodes n ON nodes_fts.rowid = n.rowid
                            WHERE nodes_fts MATCH ?
                              AND n.deleted_at IS NULL
                            ORDER BY bm25(nodes_fts)
                            LIMIT ?""",
                        (query, limit),
                    ).fetchall()
                    return [(row_to_node(r), r["_score"], r["_caller_count"]) for r in rows]
                except sqlite3.OperationalError:
                    # Invalid FTS5 query syntax — fall through to LIKE
                    pass
            rows = conn.execute(
                """SELECT n.*, 1.0 AS _score,
                          (SELECT COUNT(*) FROM edges
                           WHERE to_id = n.id AND kind = 'calls') AS _caller_count
                     FROM nodes n
                    WHERE name LIKE ? AND deleted_at IS NULL
                    LIMIT ?""",
                (f"%{query}%", limit),
            ).fetchall()
            return [(row_to_node(r), 1.0, r["_caller_count"]) for r in rows]

    triples = await asyncio.to_thread(_run)
    return [SearchResult(node=n, score=s, caller_count=c) for n, s, c in triples]


async def find_replacement_candidates(
    db: DB, *, node_id: str, path: str
) -> list[ReplacementCandidate]:
    """For a dead node, find same-file live siblings with callers as replacement candidates.

    Returns up to 3 candidates ordered by caller_count descending.
    """

    def _run() -> list[ReplacementCandidate]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """SELECT n.id, n.name, n.path,
                          (SELECT COUNT(*) FROM edges
                           WHERE to_id = n.id AND kind = 'calls') AS caller_count
                     FROM nodes n
                    WHERE n.path = ?
                      AND n.kind IN ('function', 'method')
                      AND n.deleted_at IS NULL
                      AND n.is_dead_code = 0
                      AND n.id != ?
                      AND (SELECT COUNT(*) FROM edges
                           WHERE to_id = n.id AND kind = 'calls') > 0
                    ORDER BY caller_count DESC
                    LIMIT 3""",
                (path, node_id),
            ).fetchall()
            return [
                ReplacementCandidate(
                    id=r["id"],
                    name=r["name"],
                    path=r["path"],
                    caller_count=r["caller_count"],
                )
                for r in rows
            ]

    return await asyncio.to_thread(_run)
