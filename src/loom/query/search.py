from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass

from loom.core.context import DB
from loom.core.node import Node
from loom.store.nodes import row_to_node


@dataclass
class SearchResult:
    node: Node
    score: float


async def search(query: str, db: DB, *, limit: int = 10) -> list[SearchResult]:
    """Search for nodes by name prefix or FTS5 full-text.

    Args:
        query: Search string. For FTS5 this is a full-text query; for LIKE fallback
               it matches against node names.
        db: Database context.
        limit: Maximum number of results to return.

    Returns:
        List of SearchResult ordered by relevance (highest score first).
        Soft-deleted nodes are excluded.
    """
    def _run() -> list[tuple[Node, float]]:
        with db._lock:
            conn = db.connect()
            if db._fts5:
                try:
                    rows = conn.execute(
                        """SELECT n.*, -bm25(nodes_fts) AS _score
                             FROM nodes_fts
                             JOIN nodes n ON nodes_fts.rowid = n.rowid
                            WHERE nodes_fts MATCH ?
                              AND n.deleted_at IS NULL
                            ORDER BY bm25(nodes_fts)
                            LIMIT ?""",
                        (query, limit),
                    ).fetchall()
                    return [(row_to_node(r), r["_score"]) for r in rows]
                except sqlite3.OperationalError:
                    # Invalid FTS5 query syntax — fall through to LIKE
                    pass
            rows = conn.execute(
                "SELECT * FROM nodes WHERE name LIKE ? AND deleted_at IS NULL LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [(row_to_node(r), 1.0) for r in rows]

    pairs = await asyncio.to_thread(_run)
    return [SearchResult(node=n, score=s) for n, s in pairs]
