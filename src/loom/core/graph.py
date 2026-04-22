from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from loom.core.db import connect, has_fts5, init_schema
from loom.core.edge import ConfidenceTier, Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource

DEFAULT_DB_PATH = Path.home() / ".loom" / "loom.db"


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


def _row_to_edge(row: sqlite3.Row) -> Edge:
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    return Edge(
        from_id=row["from_id"],
        to_id=row["to_id"],
        kind=EdgeType(row["kind"]),
        confidence=row["confidence"],
        confidence_tier=ConfidenceTier(row["confidence_tier"]),
        metadata=metadata,
    )


class LoomGraph:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._fts5: bool | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.db_path)
            init_schema(self._conn)
            self._fts5 = has_fts5(self._conn)
        return self._conn

    async def bulk_upsert_nodes(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        def _run() -> None:
            with self._lock:
                conn = self._connect()
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
                    """INSERT INTO nodes (id, kind, source, name, path, start_line,
                         end_line, language, content_hash, file_hash, summary,
                         is_dead_code, community_id, metadata, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         kind=excluded.kind, source=excluded.source, name=excluded.name,
                         path=excluded.path, start_line=excluded.start_line,
                         end_line=excluded.end_line, language=excluded.language,
                         content_hash=excluded.content_hash, file_hash=excluded.file_hash,
                         summary=excluded.summary, is_dead_code=excluded.is_dead_code,
                         community_id=excluded.community_id, metadata=excluded.metadata,
                         updated_at=excluded.updated_at""",
                    rows,
                )
                conn.commit()
        await asyncio.to_thread(_run)

    async def bulk_upsert_edges(self, edges: list[Edge]) -> None:
        if not edges:
            return
        def _run() -> None:
            with self._lock:
                conn = self._connect()
                rows = [
                    (
                        e.from_id, e.to_id, e.kind.value, e.confidence,
                        e.confidence_tier.value, json.dumps(e.metadata, default=str),
                    )
                    for e in edges
                ]
                conn.executemany(
                    """INSERT OR REPLACE INTO edges
                         (from_id, to_id, kind, confidence, confidence_tier, metadata)
                       VALUES (?,?,?,?,?,?)""",
                    rows,
                )
                conn.commit()
        await asyncio.to_thread(_run)

    async def replace_file(
        self, path: str, nodes: list[Node], edges: list[Edge]
    ) -> None:
        """Atomic per-file replace — single BEGIN IMMEDIATE transaction covers
        DELETE + INSERT nodes + INSERT edges. Crash between delete and insert
        rolls back cleanly; old rows remain until full write succeeds.
        """
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
            with self._lock:
                conn = self._connect()
                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Explicitly remove edges whose from_id belongs to this
                    # file (no FK cascade since cross-file edges are valid).
                    conn.execute(
                        "DELETE FROM edges WHERE from_id IN "
                        "(SELECT id FROM nodes WHERE path = ?)",
                        (path,),
                    )
                    conn.execute("DELETE FROM nodes WHERE path = ?", (path,))
                    if node_rows:
                        conn.executemany(
                            """INSERT OR REPLACE INTO nodes
                                 (id, kind, source, name, path,
                                  start_line, end_line, language, content_hash,
                                  file_hash, summary, is_dead_code, community_id,
                                  metadata, updated_at)
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

    async def get_node(self, node_id: str) -> Node | None:
        def _run() -> Node | None:
            with self._lock:
                conn = self._connect()
                row = conn.execute(
                    "SELECT * FROM nodes WHERE id = ?", (node_id,)
                ).fetchone()
                return _row_to_node(row) if row else None
        return await asyncio.to_thread(_run)

    async def get_nodes_by_name(self, name: str, limit: int = 10) -> list[Node]:
        def _run() -> list[Node]:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT * FROM nodes WHERE name = ? LIMIT ?", (name, limit)
                ).fetchall()
                return [_row_to_node(r) for r in rows]
        return await asyncio.to_thread(_run)

    async def get_content_hashes(self) -> dict[str, str]:
        def _run() -> dict[str, str]:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT path, file_hash FROM nodes WHERE file_hash IS NOT NULL"
                ).fetchall()
                return {r["path"]: r["file_hash"] for r in rows}
        return await asyncio.to_thread(_run)

    async def get_file_hash(self, path: str) -> str | None:
        def _run() -> str | None:
            with self._lock:
                conn = self._connect()
                row = conn.execute(
                    "SELECT file_hash FROM nodes WHERE path = ? LIMIT 1", (path,)
                ).fetchone()
                return row["file_hash"] if row else None
        return await asyncio.to_thread(_run)

    async def blast_radius(self, node_id: str, depth: int = 3) -> list[Node]:
        def _run() -> list[Node]:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """
                    WITH RECURSIVE impacted(id, d) AS (
                        SELECT ?, 0
                        UNION
                        SELECT e.from_id, i.d + 1
                          FROM edges e
                          JOIN impacted i ON e.to_id = i.id
                         WHERE e.kind = 'calls' AND i.d < ?
                    )
                    SELECT n.*, i.d AS _depth
                      FROM impacted i JOIN nodes n ON n.id = i.id
                     WHERE i.id != ?
                     ORDER BY i.d, n.name
                    """,
                    (node_id, depth, node_id),
                ).fetchall()
                return [_row_to_node(r) for r in rows]
        return await asyncio.to_thread(_run)

    async def neighbors(
        self, node_id: str, depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        direction: str = "both",
    ) -> list[Node]:
        """BFS over edges. direction: 'in' (predecessors), 'out' (successors),
        'both' (union). For `get_callers` use 'in'; for `get_callees` use 'out'.
        """
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be 'in', 'out', or 'both'")
        def _run() -> list[Node]:
            with self._lock:
                conn = self._connect()
                kinds = [e.value for e in (edge_types or list(EdgeType))]
                placeholders = ",".join("?" * len(kinds))
                visited: dict[str, int] = {}
                frontier = {node_id}
                for d in range(1, depth + 1):
                    if not frontier:
                        break
                    fp = ",".join("?" * len(frontier))
                    if direction == "in":
                        sql = (
                            f"SELECT DISTINCT from_id AS other FROM edges "
                            f"WHERE to_id IN ({fp}) AND kind IN ({placeholders})"
                        )
                        params: tuple = (*frontier, *kinds)
                    elif direction == "out":
                        sql = (
                            f"SELECT DISTINCT to_id AS other FROM edges "
                            f"WHERE from_id IN ({fp}) AND kind IN ({placeholders})"
                        )
                        params = (*frontier, *kinds)
                    else:
                        sql = (
                            f"SELECT DISTINCT from_id AS other FROM edges "
                            f"WHERE to_id IN ({fp}) AND kind IN ({placeholders}) "
                            f"UNION "
                            f"SELECT DISTINCT to_id AS other FROM edges "
                            f"WHERE from_id IN ({fp}) AND kind IN ({placeholders})"
                        )
                        params = (*frontier, *kinds, *frontier, *kinds)
                    rows = conn.execute(sql, params).fetchall()
                    next_frontier = {
                        r["other"] for r in rows
                        if r["other"] not in visited and r["other"] != node_id
                    }
                    for nid in next_frontier:
                        visited[nid] = d
                    frontier = next_frontier
                if not visited:
                    return []
                ids = list(visited.keys())
                ph = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT * FROM nodes WHERE id IN ({ph})", ids
                ).fetchall()
                return [_row_to_node(r) for r in rows]
        return await asyncio.to_thread(_run)

    async def shortest_path(self, from_id: str, to_id: str) -> list[Node] | None:
        """Shortest path on CALLS subgraph via NetworkX. Returns None if no path."""
        import networkx as nx
        def _run() -> list[str] | None:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT from_id, to_id FROM edges WHERE kind = 'calls'"
                ).fetchall()
                g = nx.DiGraph()
                for r in rows:
                    g.add_edge(r["from_id"], r["to_id"])
                if from_id not in g or to_id not in g:
                    return None
                try:
                    return nx.shortest_path(g, from_id, to_id)
                except nx.NetworkXNoPath:
                    return None
        ids = await asyncio.to_thread(_run)
        if not ids:
            return None
        nodes = [await self.get_node(nid) for nid in ids]
        return [n for n in nodes if n is not None]

    async def community_members(self, community_id: str) -> list[Node]:
        def _run() -> list[Node]:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    "SELECT * FROM nodes WHERE community_id = ?", (community_id,)
                ).fetchall()
                return [_row_to_node(r) for r in rows]
        return await asyncio.to_thread(_run)

    async def god_nodes(self, limit: int = 20) -> list[tuple[Node, int]]:
        def _run() -> list[tuple[Node, int]]:
            with self._lock:
                conn = self._connect()
                rows = conn.execute(
                    """SELECT n.*, COUNT(e.id) AS _indeg
                         FROM nodes n JOIN edges e ON e.to_id = n.id
                        WHERE e.kind = 'calls'
                        GROUP BY n.id
                        ORDER BY _indeg DESC
                        LIMIT ?""",
                    (limit,),
                ).fetchall()
                return [(_row_to_node(r), r["_indeg"]) for r in rows]
        return await asyncio.to_thread(_run)

    async def search(self, query: str, limit: int = 10) -> list[Node]:
        def _run() -> list[Node]:
            with self._lock:
                conn = self._connect()
                if self._fts5:
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
        return await asyncio.to_thread(_run)

    async def stats(self) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with self._lock:
                conn = self._connect()
                n_total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                e_total = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                by_kind = {
                    r["kind"]: r["c"]
                    for r in conn.execute(
                        "SELECT kind, COUNT(*) AS c FROM nodes GROUP BY kind"
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
        return await asyncio.to_thread(_run)
