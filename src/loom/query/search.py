from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loom.core.context import DB
from loom.core.node import Node
from loom.store.nodes import _row_to_node


@dataclass
class SearchResult:
    node: Node
    score: float


async def search(query: str, db: DB, *, limit: int = 10) -> list[SearchResult]:
    """Search for nodes by name prefix or FTS5 full-text."""
    def _run() -> list[Node]:
        with db._lock:
            conn = db.connect()
            if db._fts5:
                rows = conn.execute(
                    """SELECT n.* FROM nodes_fts f
                         JOIN nodes n ON n.rowid = f.rowid
                        WHERE nodes_fts MATCH ? LIMIT ?""",
                    (query, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes WHERE name LIKE ? LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            return [_row_to_node(r) for r in rows]

    nodes = await asyncio.to_thread(_run)
    return [SearchResult(node=n, score=1.0) for n in nodes]
