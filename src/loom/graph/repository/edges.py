"""EdgeRepository — synchronous edge persistence layer.

Extracted from src/loom/store/edges.py (async), converted to pure synchronous
methods. Also adds get_for_node and delete_for_path which are new query methods.
"""

from __future__ import annotations

import json
from typing import Any

from loom.graph.db import DB
from loom.graph.models import Edge, EdgeType


class EdgeRepository:
    """Synchronous CRUD operations for the edges table."""

    def __init__(self, db: DB) -> None:
        self._db = db

    @staticmethod
    def _row_to_edge(r: Any) -> Edge:
        return Edge(
            from_id=r["from_id"],
            to_id=r["to_id"],
            kind=EdgeType(r["kind"]),
            confidence=r["confidence"],
            confidence_tier=r["confidence_tier"],
            metadata=json.loads(r["metadata"]) if r["metadata"] else {},
            description=r["description"],
        )

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
                e.description,
            )
            for e in edges
        ]

        with self._db._lock:
            conn = self._db.connect()
            conn.executemany(
                """INSERT OR REPLACE INTO edges
                     (from_id, to_id, kind, confidence, confidence_tier, metadata, description)
                   VALUES (?,?,?,?,?,?,?)""",
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
                    """SELECT from_id, to_id, kind, confidence, confidence_tier, metadata,
                              description
                         FROM edges
                        WHERE (from_id = ? OR to_id = ?)
                          AND kind = ?""",
                    (node_id, node_id, kind.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT from_id, to_id, kind, confidence, confidence_tier, metadata,
                              description
                         FROM edges
                        WHERE from_id = ? OR to_id = ?""",
                    (node_id, node_id),
                ).fetchall()

        return [self._row_to_edge(r) for r in rows]

    def edge_exists(self, from_id: str, to_id: str, kind: EdgeType | str) -> bool:
        """Return True if an edge with the given from_id, to_id, and kind exists.

        Args:
            from_id: Source node id.
            to_id: Target node id.
            kind: EdgeType (or str-compatible value).

        Returns:
            True if a matching edge exists, False otherwise.
        """
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute(
                "SELECT 1 FROM edges WHERE from_id = ? AND to_id = ? AND kind = ? LIMIT 1",
                (from_id, to_id, kind.value if hasattr(kind, "value") else str(kind)),
            ).fetchone()
        return row is not None

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

    def get_all(self) -> list[Edge]:
        """Return all edges. WARNING: in-memory; avoid on graphs > 100k edges."""
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT from_id, to_id, kind, confidence, confidence_tier, description, metadata "
                "FROM edges"
            ).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def iter_pairs(self, kind=None):
        """Generator yielding (from_id, to_id) tuples. Memory-efficient for Brandes."""
        sql = "SELECT from_id, to_id FROM edges"
        params: tuple = ()
        if kind is not None:
            kind_val = kind.value if hasattr(kind, "value") else str(kind)
            sql += " WHERE kind = ?"
            params = (kind_val,)
        with self._db._lock:
            conn = self._db.connect()
            for row in conn.execute(sql, params):
                yield (row["from_id"], row["to_id"])
