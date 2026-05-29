"""NodeRepository — synchronous node persistence layer.

Extracted from src/loom/store/nodes.py (async) and
src/loom/query/node_lookup.py (async), converted to pure synchronous methods.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from loom.graph.db import DB
from loom.graph.models import Edge, Node, NodeKind, NodeSource

_TOKENS_PER_LINE = 15  # avg chars/line ~60, chars/token ~4 → 15 tokens/line


# ---------------------------------------------------------------------------
# Errors (ported from query/node_lookup.py)
# ---------------------------------------------------------------------------


class AmbiguousNodeError(Exception):
    def __init__(self, name: str, count: int) -> None:
        super().__init__(f"Ambiguous target: {count} nodes named {name!r}")
        self.count = count


class NodeNotFoundError(Exception):
    pass


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _calc_token_count(n: Node) -> int | None:
    """Estimate tokens in this node's source span. Returns None for file/community nodes."""
    if n.kind.value in ("file", "community"):
        return None
    if n.start_line is None or n.end_line is None:
        return None
    return max(1, n.end_line - n.start_line + 1) * _TOKENS_PER_LINE


def row_to_node(row: sqlite3.Row) -> Node:
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    node = Node(
        id=row["id"],
        kind=NodeKind(row["kind"]),
        source=NodeSource(row["source"]),
        name=row["name"],
        path=row["path"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        language=row["language"],
        content_hash=row["content_hash"],
        file_hash=row["file_hash"],
        file_mtime=row["file_mtime"],
        summary=row["summary"],
        summary_hash=row["summary_hash"] if "summary_hash" in row.keys() else None,  # noqa: SIM118
        token_count=row["token_count"] if "token_count" in row.keys() else None,  # noqa: SIM118
        community_id=row["community_id"],
        metadata=metadata,
    )
    if "_depth" in row.keys():  # noqa: SIM118 — sqlite3.Row needs .keys()
        node.depth = row["_depth"]
    return node


# ---------------------------------------------------------------------------
# NodeRepository
# ---------------------------------------------------------------------------


class NodeRepository:
    """Synchronous CRUD operations for the nodes table."""

    def __init__(self, db: DB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, node_id: str) -> Node | None:
        """Return a single node by its exact id, or None."""
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return row_to_node(row) if row else None

    def get_by_name(self, name: str, limit: int = 10) -> list[Node]:
        """Return nodes whose name matches exactly."""
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT * FROM nodes WHERE name = ? LIMIT ?", (name, limit)
            ).fetchall()
            return [row_to_node(r) for r in rows]

    def get_batch(self, node_ids: list[str]) -> list[Node]:
        """Return multiple nodes by id. Missing ids are silently omitted."""
        if not node_ids:
            return []
        with self._db._lock:
            conn = self._db.connect()
            placeholders = ",".join("?" * len(node_ids))
            rows = conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({placeholders})", node_ids
            ).fetchall()
            return [row_to_node(r) for r in rows]

    def get_content_hashes(self) -> dict[str, tuple[str, float | None]]:
        """Return {rel_path: (file_hash, file_mtime)} for all indexed files."""
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT path, file_hash, file_mtime FROM nodes "
                "WHERE kind = 'file' AND file_hash IS NOT NULL AND deleted_at IS NULL"
            ).fetchall()
            return {r["path"]: (r["file_hash"], r["file_mtime"]) for r in rows}

    def get_file_hash(self, path: str) -> str | None:
        """Return the file_hash for a given path, or None."""
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute(
                "SELECT file_hash FROM nodes WHERE path = ? LIMIT 1", (path,)
            ).fetchone()
            return row["file_hash"] if row else None

    def count_by_kind(self) -> dict[str, Any]:
        """Return node/edge counts broken down by kind."""
        with self._db._lock:
            conn = self._db.connect()
            n_total = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
            ).fetchone()[0]
            e_total = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            by_kind = {
                r["kind"]: r["c"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM nodes WHERE deleted_at IS NULL GROUP BY kind"
                ).fetchall()
            }
            by_edge = {
                r["kind"]: r["c"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS c FROM edges GROUP BY kind"
                ).fetchall()
            }
            return {
                "nodes": n_total,
                "edges": e_total,
                "nodes_by_kind": by_kind,
                "edges_by_kind": by_edge,
            }

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert(
        self,
        nodes: list[Node],
        edges: list[Edge] | None = None,
        rel_path: str | None = None,
    ) -> int:
        """Insert or update nodes (and optionally edges) atomically.

        When rel_path is provided, performs an atomic file-level replacement:
        existing nodes (and their outgoing edges) for that path are deleted
        before inserting the new rows, and agent summaries are preserved for
        any node id that survives the re-parse.

        When rel_path is None, performs a plain bulk upsert (no deletions).

        Returns:
            Number of nodes written.
        """
        if not nodes:
            return 0

        now = int(time.time())
        node_rows = [
            (
                n.id,
                n.kind.value,
                n.source.value,
                n.name,
                n.path,
                n.start_line,
                n.end_line,
                n.language,
                n.content_hash,
                n.file_hash,
                n.file_mtime,
                n.summary,
                _calc_token_count(n),
                n.community_id,
                json.dumps(n.metadata, default=str),
                now,
            )
            for n in nodes
        ]

        if rel_path is not None:
            # Atomic file-level replacement (ported from replace_file)
            edge_rows: list[tuple] = []
            if edges:
                edge_rows = [
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
                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Save existing agent summaries before replacing (by node id)
                    saved: dict[str, tuple[str, str | None]] = {
                        r["id"]: (r["summary"], r["summary_hash"])
                        for r in conn.execute(
                            "SELECT id, summary, summary_hash FROM nodes "
                            "WHERE path = ? AND summary IS NOT NULL",
                            (rel_path,),
                        ).fetchall()
                    }

                    conn.execute(
                        "DELETE FROM edges WHERE from_id IN (SELECT id FROM nodes WHERE path = ?)",
                        (rel_path,),
                    )
                    conn.execute("DELETE FROM nodes WHERE path = ?", (rel_path,))

                    if node_rows:
                        conn.executemany(
                            """INSERT OR REPLACE INTO nodes
                                 (id, kind, source, name, path, start_line, end_line,
                                  language, content_hash, file_hash, file_mtime, summary,
                                  token_count, community_id, metadata, updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            node_rows,
                        )
                    if edge_rows:
                        conn.executemany(
                            """INSERT OR REPLACE INTO edges
                                 (from_id, to_id, kind, confidence,
                                  confidence_tier, metadata)
                               VALUES (?,?,?,?,?,?)""",
                            edge_rows,
                        )

                    # Restore agent summaries that survived re-parse
                    for node_id, (summary, summary_hash) in saved.items():
                        conn.execute(
                            "UPDATE nodes SET summary = ?, summary_hash = ? "
                            "WHERE id = ? AND summary IS NULL",
                            (summary, summary_hash, node_id),
                        )

                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        else:
            # Plain bulk upsert (ported from bulk_upsert_nodes)
            with self._db._lock:
                conn = self._db.connect()
                conn.executemany(
                    """INSERT INTO nodes
                         (id, kind, source, name, path, start_line, end_line,
                          language, content_hash, file_hash, file_mtime, summary,
                          token_count, community_id, metadata, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         kind=excluded.kind, source=excluded.source, name=excluded.name,
                         path=excluded.path, start_line=excluded.start_line,
                         end_line=excluded.end_line, language=excluded.language,
                         content_hash=excluded.content_hash, file_hash=excluded.file_hash,
                         file_mtime=excluded.file_mtime,
                         summary=CASE
                             WHEN excluded.summary IS NOT NULL AND nodes.summary IS NULL
                             THEN excluded.summary
                             ELSE nodes.summary
                         END,
                         token_count=COALESCE(excluded.token_count, nodes.token_count),
                         community_id=excluded.community_id, metadata=excluded.metadata,
                         updated_at=CASE
                             WHEN excluded.content_hash IS NOT NULL
                                  AND excluded.content_hash != COALESCE(nodes.content_hash, '')
                             THEN excluded.updated_at
                             ELSE nodes.updated_at
                         END""",
                    node_rows,
                )
                conn.commit()

        return len(nodes)

    def store_summary(
        self,
        node_id: str,
        summary: str,
        *,
        force: bool = False,
        author: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Write agent summary for a node.

        Skips write when summary already exists and content_hash unchanged.
        Pass force=True to overwrite regardless.

        Returns:
            Dict with keys: found (bool), updated (bool), skipped (bool).
        """
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute(
                "SELECT summary, summary_hash, content_hash FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                return {"found": False, "updated": False, "skipped": False}

            # Skip if fresh: summary exists and hash matches current content
            if not force and row["summary"] and row["summary_hash"] == row["content_hash"]:
                return {"found": True, "updated": False, "skipped": True}

            conn.execute(
                """UPDATE nodes
                      SET summary = ?,
                          summary_hash = content_hash,
                          updated_at = ?,
                          summary_author = ?,
                          summary_session = ?
                    WHERE id = ?""",
                (summary.strip(), int(time.time()), author, session_id, node_id),
            )
            conn.commit()
            return {"found": True, "updated": True, "skipped": False}

    def mark_deleted(self, path: str) -> int:
        """Soft-delete all active nodes for a file path.

        Returns:
            Number of nodes marked deleted.
        """
        with self._db._lock:
            conn = self._db.connect()
            cur = conn.execute(
                "UPDATE nodes SET deleted_at = ? WHERE path = ? AND deleted_at IS NULL",
                (int(time.time()), path),
            )
            conn.commit()
            return cur.rowcount

    def prune_tombstones(self, older_than_days: int = 30) -> int:
        """Permanently delete soft-deleted nodes older than N days.

        Returns:
            Number of nodes permanently deleted.
        """
        cutoff = int(time.time()) - (older_than_days * 86400)
        with self._db._lock:
            conn = self._db.connect()
            cur = conn.execute(
                "DELETE FROM nodes WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    def update_layer(self, node_id: str, layer: str | None) -> None:
        """Set the layer field for a node.

        Args:
            node_id: Target node id.
            layer: Layer string value (or None to clear).
        """
        with self._db._lock:
            conn = self._db.connect()
            conn.execute("UPDATE nodes SET layer = ? WHERE id = ?", (layer, node_id))
            conn.commit()

    def update_bridge_score(self, node_id: str, score: float | None) -> None:
        """Set the bridge_score field for a node.

        Args:
            node_id: Target node id.
            score: Bridge score value (or None to clear).
        """
        with self._db._lock:
            conn = self._db.connect()
            conn.execute("UPDATE nodes SET bridge_score = ? WHERE id = ?", (score, node_id))
            conn.commit()

    def update_language_notes(self, node_id: str, notes: str | None) -> None:
        """Set the language_notes field for a node.

        Args:
            node_id: Target node id.
            notes: Language notes text (or None to clear).
        """
        with self._db._lock:
            conn = self._db.connect()
            conn.execute("UPDATE nodes SET language_notes = ? WHERE id = ?", (notes, node_id))
            conn.commit()

    # ------------------------------------------------------------------
    # ID resolution (ported from query/node_lookup.py)
    # ------------------------------------------------------------------

    def resolve_id(
        self,
        target: str,
        kind: NodeKind | None = None,
        limit: int = 2,
    ) -> str | None:
        """Resolve a node name or full id to a canonical node id.

        If target contains ':', it is assumed to be a full id and returned as-is.
        Otherwise, looks up nodes by name. If kind is given, filters to that kind.
        Returns the id when exactly one match is found, None otherwise.
        """
        if ":" in target:
            return target
        nodes = self.get_by_name(target, limit=limit)
        if kind is not None:
            nodes = [n for n in nodes if n.kind == kind]
        if len(nodes) == 1:
            return nodes[0].id
        return None
