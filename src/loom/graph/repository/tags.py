"""TagRepository — node tag storage with system/agent source tracking."""

from __future__ import annotations

from loom.graph.db import DB


class TagRepository:
    def __init__(self, db: DB) -> None:
        self._db = db

    def add_tags(self, node_id: str, tags: list[str], source: str = "system") -> None:
        """Insert tags + rebuild tags_normalized atomically. Deduplicates."""
        if not tags:
            return
        with self._db._lock:
            conn = self._db.connect()
            conn.executemany(
                """INSERT OR IGNORE INTO node_tags (node_id, tag, source)
                   VALUES (?, ?, ?)""",
                [(node_id, tag, source) for tag in tags],
            )
            self._rebuild_normalized(conn, node_id)
            conn.commit()

    def get_tags(self, node_id: str) -> list[str]:
        """Return all tags for a node (both sources), deduplicated, sorted."""
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT DISTINCT tag FROM node_tags WHERE node_id = ? ORDER BY tag",
                (node_id,),
            ).fetchall()
            return [r[0] for r in rows]

    def remove_tags(self, node_id: str, tags: list[str], source: str = "system") -> None:
        """Remove specific tags for a source + rebuild tags_normalized."""
        if not tags:
            return
        with self._db._lock:
            conn = self._db.connect()
            placeholders = ",".join("?" * len(tags))
            conn.execute(
                "DELETE FROM node_tags WHERE node_id = ? AND source = ? "
                f"AND tag IN ({placeholders})",
                [node_id, source, *tags],
            )
            self._rebuild_normalized(conn, node_id)
            conn.commit()

    def clear_node_tags(self, node_id: str, source: str = "system") -> None:
        """Wipe all tags for a node/source combo. Called on re-index (source='system')."""
        with self._db._lock:
            conn = self._db.connect()
            conn.execute(
                "DELETE FROM node_tags WHERE node_id = ? AND source = ?",
                (node_id, source),
            )
            self._rebuild_normalized(conn, node_id)
            conn.commit()

    def clear_bulk(self, node_ids: list[str], source: str = "system") -> None:
        """Clear system tags for multiple nodes (used during re-index)."""
        if not node_ids:
            return
        with self._db._lock:
            conn = self._db.connect()
            placeholders = ",".join("?" * len(node_ids))
            conn.execute(
                f"DELETE FROM node_tags WHERE node_id IN ({placeholders}) AND source = ?",
                [*node_ids, source],
            )
            # Rebuild normalized for all affected nodes
            for node_id in node_ids:
                self._rebuild_normalized(conn, node_id)
            conn.commit()

    def clear_by_tags(self, tags: list[str], source: str = "system") -> int:
        """Remove all (node_id, tag, source) rows matching any tag in `tags`.

        Returns the number of rows deleted. Rebuilds tags_normalized for affected nodes.
        """
        if not tags:
            return 0
        placeholders = ",".join("?" * len(tags))
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                f"SELECT DISTINCT node_id FROM node_tags WHERE tag IN ({placeholders}) AND source = ?",
                (*tags, source),
            ).fetchall()
            affected = [r["node_id"] for r in rows]
            cur = conn.execute(
                f"DELETE FROM node_tags WHERE tag IN ({placeholders}) AND source = ?",
                (*tags, source),
            )
            deleted = cur.rowcount
            for node_id in affected:
                self._rebuild_normalized(conn, node_id)
            conn.commit()
        return deleted

    def _rebuild_normalized(self, conn, node_id: str) -> None:
        """Rebuild tags_normalized on nodes table from node_tags. Internal only."""
        rows = conn.execute(
            "SELECT DISTINCT tag FROM node_tags WHERE node_id = ? ORDER BY tag",
            (node_id,),
        ).fetchall()
        normalized = " ".join(r[0] for r in rows)
        conn.execute(
            "UPDATE nodes SET tags_normalized = ? WHERE id = ?",
            (normalized, node_id),
        )
