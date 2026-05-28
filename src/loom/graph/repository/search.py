"""SearchRepository — synchronous search layer.

Extracted from src/loom/query/search.py (async), converted to pure synchronous
methods.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from loom.graph.db import DB
from loom.graph.models import Node
from loom.graph.repository.nodes import row_to_node


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


class SearchRepository:
    """Synchronous full-text and LIKE search operations."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for nodes by name prefix or FTS5 full-text.

        Auto-picks FTS5 vs LIKE based on database capabilities.

        Args:
            query: Search string. For FTS5 this is a full-text query; for LIKE
                   fallback it matches against node names.
            limit: Maximum number of results to return.

        Returns:
            List of SearchResult ordered by relevance (highest score first).
            Soft-deleted nodes are excluded. caller_count included for ranking.
        """
        with self._db._lock:
            conn = self._db.connect()
            if self._db._fts5:
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
                    return [
                        SearchResult(
                            node=row_to_node(r), score=r["_score"], caller_count=r["_caller_count"]
                        )
                        for r in rows
                    ]
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
            return [
                SearchResult(
                    node=row_to_node(r), score=1.0, caller_count=r["_caller_count"]
                )
                for r in rows
            ]

    def find_replacements(self, node_id: str) -> list[ReplacementCandidate]:
        """For a dead node, find same-file live siblings with callers as replacement candidates.

        Uses the node's path to find other functions/methods in the same file
        that are alive (not dead code) and have at least one caller.

        Returns up to 3 candidates ordered by caller_count descending.
        """
        with self._db._lock:
            conn = self._db.connect()
            # Look up the node's path first
            row = conn.execute(
                "SELECT path FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return []
            path = row["path"]

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
