from __future__ import annotations

import asyncio
from typing import Any

import networkx as nx

from loom.graph.db import DB
from loom.graph.models import EdgeType
from loom.graph.models import Node
from loom.store.nodes import get_node as _get_node
from loom.store.nodes import row_to_node


async def neighbors(
    db: DB,
    node_id: str,
    depth: int = 1,
    edge_types: list[EdgeType] | None = None,
    direction: str = "both",
) -> list[Node]:
    if direction not in {"in", "out", "both"}:
        raise ValueError("direction must be 'in', 'out', or 'both'")

    def _run() -> list[Node]:
        with db._lock:
            conn = db.connect()
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
                    r["other"] for r in rows if r["other"] not in visited and r["other"] != node_id
                }
                for nid in next_frontier:
                    visited[nid] = d
                frontier = next_frontier
            if not visited:
                return []
            ids = list(visited.keys())
            ph = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({ph}) AND deleted_at IS NULL", ids
            ).fetchall()
            return [row_to_node(r) for r in rows]

    return await asyncio.to_thread(_run)


async def blast_radius(
    db: DB,
    node_id: str,
    depth: int = 3,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Node], int]:
    """Return paginated callers up to `depth` hops.

    Returns (nodes_slice, total_count).
    Two-pass: IDs-only CTE first (no joins), then full rows for slice only.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    def _run() -> tuple[list[Node], int]:
        with db._lock:
            conn = db.connect()
            # Pass 1: IDs only — cheap, no node joins
            id_rows = conn.execute(
                """
                WITH RECURSIVE impacted(id, d) AS (
                    SELECT ?, 0
                    UNION
                    SELECT e.from_id, i.d + 1
                      FROM edges e
                      JOIN impacted i ON e.to_id = i.id
                     WHERE e.kind = ? AND i.d < ?
                )
                SELECT id FROM impacted WHERE id != ?
                """,
                (node_id, EdgeType.CALLS.value, depth, node_id),
            ).fetchall()
            all_ids = [r["id"] for r in id_rows]
            total = len(all_ids)

            # Pass 2: full rows for slice only
            slice_ids = all_ids[offset : offset + limit]
            if not slice_ids:
                return [], total

            ph = ",".join("?" * len(slice_ids))
            rows = conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({ph}) AND deleted_at IS NULL",
                slice_ids,
            ).fetchall()
            nodes = [row_to_node(r) for r in rows]
            return nodes, total

    return await asyncio.to_thread(_run)


async def shortest_path(db: DB, from_id: str, to_id: str) -> list[Node] | None:
    def _run() -> list[str] | None:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT from_id, to_id FROM edges WHERE kind = ?",
                (EdgeType.CALLS.value,),
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
    nodes = [await _get_node(db, nid) for nid in ids]
    return [n for n in nodes if n is not None]


async def community_members(db: DB, community_id: str) -> list[Node]:
    def _run() -> list[Node]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                "SELECT * FROM nodes WHERE community_id = ? AND deleted_at IS NULL",
                (community_id,),
            ).fetchall()
            return [row_to_node(r) for r in rows]

    return await asyncio.to_thread(_run)


async def god_nodes(db: DB, limit: int = 20) -> list[tuple[Node, int]]:
    def _run() -> list[tuple[Node, int]]:
        with db._lock:
            conn = db.connect()
            rows = conn.execute(
                """SELECT n.*, COUNT(e.id) AS _indeg
                     FROM nodes n JOIN edges e ON e.to_id = n.id
                    WHERE e.kind = ?
                      AND n.deleted_at IS NULL
                    GROUP BY n.id
                    ORDER BY _indeg DESC
                    LIMIT ?""",
                (EdgeType.CALLS.value, limit),
            ).fetchall()
            return [(row_to_node(r), r["_indeg"]) for r in rows]

    return await asyncio.to_thread(_run)


async def stats(db: DB) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        with db._lock:
            conn = db.connect()
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

    return await asyncio.to_thread(_run)
