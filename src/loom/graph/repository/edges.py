"""EdgeRepository — synchronous edge persistence layer.

Extracted from src/loom/store/edges.py (async), converted to pure synchronous
methods. Also adds get_for_node and delete_for_path which are new query methods.
"""
from __future__ import annotations

import json

from loom.graph.db import DB
from loom.graph.models import Edge, EdgeType


class EdgeRepository:
    """Synchronous CRUD operations for the edges table."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def upsert(self, edges: list[Edge]) -> int:
        """Insert or replace edges in bulk.

        Args:
            edges: List of Edge objects to persist.

        Returns:
            Number of edges written.
        """
        if not edges:
            return 0

        rows = [
            (
                e.from_id,
                e.to_id,
                e.kind.value,
                e.confidence,
                e.confidence_tier.value,
                json.dumps(e.metadata, default=str),
            )
            for e in edges
        ]

        with self._db._lock:
            conn = self._db.connect()
            conn.executemany(
                """INSERT OR REPLACE INTO edges
                     (from_id, to_id, kind, confidence, confidence_tier, metadata)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )
            conn.commit()

        return len(edges)

    def get_for_node(self, node_id: str, kind: EdgeType | None = None) -> list[Edge]:
        """Return all edges where from_id or to_id matches node_id.

        Args:
            node_id: Node to query edges for.
            kind: Optional EdgeType filter.

        Returns:
            List of matching Edge objects.
        """
        with self._db._lock:
            conn = self._db.connect()
            if kind is not None:
                rows = conn.execute(
                    """SELECT from_id, to_id, kind, confidence, confidence_tier, metadata
                         FROM edges
                        WHERE (from_id = ? OR to_id = ?)
                          AND kind = ?""",
                    (node_id, node_id, kind.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT from_id, to_id, kind, confidence, confidence_tier, metadata
                         FROM edges
                        WHERE from_id = ? OR to_id = ?""",
                    (node_id, node_id),
                ).fetchall()

        return [
            Edge(
                from_id=r["from_id"],
                to_id=r["to_id"],
                kind=EdgeType(r["kind"]),
                confidence=r["confidence"],
                confidence_tier=r["confidence_tier"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else {},
            )
            for r in rows
        ]

    def delete_for_path(self, path: str) -> int:
        """Delete edges whose from_id or to_id contains the given path.

        Args:
            path: File path fragment to match against node ids.

        Returns:
            Number of edges deleted.
        """
        pattern = f"%{path}%"
        with self._db._lock:
            conn = self._db.connect()
            cur = conn.execute(
                "DELETE FROM edges WHERE from_id LIKE ? OR to_id LIKE ?",
                (pattern, pattern),
            )
            conn.commit()
        return cur.rowcount
