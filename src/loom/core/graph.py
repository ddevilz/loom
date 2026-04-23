from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any

from loom.core.context import DB
from loom.core.edge import ConfidenceTier, Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.store import edges as _edge_store
from loom.store import nodes as _node_store
from loom.store.nodes import _row_to_node

DEFAULT_DB_PATH = Path.home() / ".loom" / "loom.db"


def _row_to_edge(row: sqlite3.Row) -> Edge:
    import json
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
        self._db = DB(path=self.db_path)
        self._db._lock = self._lock

    def _connect(self) -> sqlite3.Connection:
        conn = self._db.connect()
        self._conn = self._db._conn
        self._fts5 = self._db._fts5
        return conn

    async def bulk_upsert_nodes(self, nodes: list[Node]) -> None:
        await _node_store.bulk_upsert_nodes(self._db, nodes)

    async def bulk_upsert_edges(self, edges: list[Edge]) -> None:
        await _edge_store.bulk_upsert_edges(self._db, edges)

    async def replace_file(
        self, path: str, nodes: list[Node], edges: list[Edge]
    ) -> None:
        await _node_store.replace_file(self._db, path, nodes, edges)

    async def get_node(self, node_id: str) -> Node | None:
        return await _node_store.get_node(self._db, node_id)

    async def get_nodes_by_name(self, name: str, limit: int = 10) -> list[Node]:
        return await _node_store.get_nodes_by_name(self._db, name, limit)

    async def get_content_hashes(self) -> dict[str, str]:
        return await _node_store.get_content_hashes(self._db)

    async def get_file_hash(self, path: str) -> str | None:
        return await _node_store.get_file_hash(self._db, path)

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

    async def update_summary(self, node_id: str, summary: str) -> bool:
        """Write agent-generated understanding to a node's summary field.

        Returns True if a row was updated, False if node_id not found.
        """
        def _run() -> bool:
            with self._lock:
                conn = self._connect()
                cur = conn.execute(
                    "UPDATE nodes SET summary = ?, updated_at = ? WHERE id = ?",
                    (summary.strip(), int(time.time()), node_id),
                )
                conn.commit()
                return cur.rowcount > 0
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
