from __future__ import annotations

import asyncio
import json
import sqlite3
import time

from loom.core.context import DB
from loom.core.edge import ConfidenceTier, Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource


def _row_to_node(row: sqlite3.Row) -> Node:
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
        summary=row["summary"],
        is_dead_code=bool(row["is_dead_code"]),
        community_id=row["community_id"],
        metadata=metadata,
    )
    if "_depth" in row.keys():  # noqa: SIM118 — sqlite3.Row needs .keys()
        node.depth = row["_depth"]
    return node


async def get_node(db: DB, node_id: str) -> Node | None:
    def _run() -> Node | None:
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            return _row_to_node(row) if row else None
    return await asyncio.to_thread(_run)


async def get_nodes_by_name(db: DB, name: str, limit: int = 10) -> list[Node]:
    def _run() -> list[Node]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT * FROM nodes WHERE name = ? LIMIT ?", (name, limit)
            ).fetchall()
            return [_row_to_node(r) for r in rows]
    return await asyncio.to_thread(_run)


async def get_content_hashes(db: DB) -> dict[str, str]:
    def _run() -> dict[str, str]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT path, file_hash FROM nodes WHERE file_hash IS NOT NULL"
            ).fetchall()
            return {r["path"]: r["file_hash"] for r in rows}
    return await asyncio.to_thread(_run)


async def get_file_hash(db: DB, path: str) -> str | None:
    def _run() -> str | None:
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT file_hash FROM nodes WHERE path = ? LIMIT 1", (path,)
            ).fetchone()
            return row["file_hash"] if row else None
    return await asyncio.to_thread(_run)


async def update_summary(db: DB, node_id: str, summary: str) -> bool:
    def _run() -> bool:
        with db._lock:
            conn = db.connect()
            cur = conn.execute(
                """UPDATE nodes
                      SET summary = ?,
                          summary_hash = content_hash,
                          updated_at = ?
                    WHERE id = ?""",
                (summary.strip(), int(time.time()), node_id),
            )
            conn.commit()
            return cur.rowcount > 0
    return await asyncio.to_thread(_run)


async def mark_nodes_deleted(db: DB, path: str) -> int:
    """Soft-delete all active nodes for a file path.

    Args:
        db: Database context.
        path: Relative file path (e.g. 'src/auth.py').

    Returns:
        Number of nodes marked deleted.
    """
    def _run() -> int:
        with db._lock:
            conn = db.connect()
            cur = conn.execute(
                "UPDATE nodes SET deleted_at = ? WHERE path = ? AND deleted_at IS NULL",
                (int(time.time()), path),
            )
            conn.commit()
            return cur.rowcount
    return await asyncio.to_thread(_run)


async def prune_tombstones(db: DB, *, older_than_days: int = 30) -> int:
    """Permanently delete soft-deleted nodes older than N days.

    Args:
        db: Database context.
        older_than_days: Age threshold in days.

    Returns:
        Number of nodes permanently deleted.
    """
    cutoff = int(time.time()) - (older_than_days * 86400)

    def _run() -> int:
        with db._lock:
            conn = db.connect()
            cur = conn.execute(
                "DELETE FROM nodes WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount
    return await asyncio.to_thread(_run)


async def get_summaries(db: DB, limit: int = 20) -> list[sqlite3.Row]:
    def _run() -> list[sqlite3.Row]:
        with db._lock:
            conn = db.connect()
            return conn.execute(
                "SELECT name, path, summary FROM nodes "
                "WHERE summary IS NOT NULL AND kind NOT IN ('file', 'community') "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return await asyncio.to_thread(_run)


async def bulk_upsert_nodes(db: DB, nodes: list[Node]) -> None:
    if not nodes:
        return

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            now = int(time.time())
            rows = [
                (
                    n.id, n.kind.value, n.source.value, n.name, n.path,
                    n.start_line, n.end_line, n.language, n.content_hash,
                    n.file_hash, n.summary, int(n.is_dead_code), n.community_id,
                    json.dumps(n.metadata, default=str), now,
                )
                for n in nodes
            ]
            conn.executemany(
                """INSERT INTO nodes
                     (id, kind, source, name, path, start_line, end_line,
                      language, content_hash, file_hash, summary, is_dead_code,
                      community_id, metadata, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     kind=excluded.kind, source=excluded.source, name=excluded.name,
                     path=excluded.path, start_line=excluded.start_line,
                     end_line=excluded.end_line, language=excluded.language,
                     content_hash=excluded.content_hash, file_hash=excluded.file_hash,
                     summary=CASE
                         WHEN excluded.summary IS NOT NULL AND nodes.summary IS NULL
                         THEN excluded.summary
                         ELSE nodes.summary
                     END,
                     is_dead_code=excluded.is_dead_code,
                     community_id=excluded.community_id, metadata=excluded.metadata,
                     updated_at=CASE
                         WHEN excluded.content_hash IS NOT NULL
                              AND excluded.content_hash != COALESCE(nodes.content_hash, '')
                         THEN excluded.updated_at
                         ELSE nodes.updated_at
                     END""",
                rows,
            )
            conn.commit()

    await asyncio.to_thread(_run)


async def replace_file(
    db: DB, path: str, nodes: list[Node], edges: list[Edge]
) -> None:
    now = int(time.time())
    node_rows = [
        (
            n.id, n.kind.value, n.source.value, n.name, n.path,
            n.start_line, n.end_line, n.language, n.content_hash,
            n.file_hash, n.summary, int(n.is_dead_code), n.community_id,
            json.dumps(n.metadata, default=str), now,
        )
        for n in nodes
    ]
    edge_rows = [
        (
            e.from_id, e.to_id, e.kind.value, e.confidence,
            e.confidence_tier.value, json.dumps(e.metadata, default=str),
        )
        for e in edges
    ]

    def _run() -> None:
        with db._lock:
            conn = db.connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    "DELETE FROM edges WHERE from_id IN "
                    "(SELECT id FROM nodes WHERE path = ?)",
                    (path,),
                )
                conn.execute("DELETE FROM nodes WHERE path = ?", (path,))
                if node_rows:
                    conn.executemany(
                        """INSERT OR REPLACE INTO nodes
                             (id, kind, source, name, path, start_line, end_line,
                              language, content_hash, file_hash, summary,
                              is_dead_code, community_id, metadata, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    await asyncio.to_thread(_run)


def get_export_rows(db: DB) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """Return (node_rows, edge_rows) for HTML graph export. Synchronous — call inside to_thread."""
    with db._lock:
        conn = db.connect()
        node_rows = conn.execute(
            "SELECT id, kind, name, path, language, is_dead_code FROM nodes"
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT from_id, to_id, kind FROM edges"
        ).fetchall()
    return node_rows, edge_rows
