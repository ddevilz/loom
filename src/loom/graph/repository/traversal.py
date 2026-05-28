"""TraversalRepository — synchronous graph traversal layer.

Extracted from src/loom/query/traversal.py (async) and
src/loom/query/blast_radius.py (async), converted to pure synchronous methods.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from loom.graph.db import DB
from loom.graph.models import EdgeType, Node
from loom.graph.repository.nodes import row_to_node


class TraversalRepository:
    """Synchronous graph traversal operations."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        direction: str = "both",
    ) -> list[Node]:
        """Return nodes reachable from node_id within depth hops.

        Args:
            node_id: Starting node id.
            depth: Max traversal depth.
            edge_types: Edge kinds to follow. Defaults to all.
            direction: 'in', 'out', or 'both'.

        Returns:
            List of reachable nodes (excluding the starting node).
        """
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be 'in', 'out', or 'both'")

        with self._db._lock:
            conn = self._db.connect()
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

    def callers(self, node_id: str) -> list[Node]:
        """Convenience: return nodes that call node_id (direction='in', edge_types=[CALLS])."""
        return self.neighbors(node_id, depth=1, edge_types=[EdgeType.CALLS], direction="in")

    def callees(self, node_id: str) -> list[Node]:
        """Convenience: return nodes that node_id calls (direction='out', edge_types=[CALLS])."""
        return self.neighbors(node_id, depth=1, edge_types=[EdgeType.CALLS], direction="out")

    def shortest_path(self, from_id: str, to_id: str) -> list[str] | None:
        """Find shortest path between two nodes using CALLS edges.

        Uses NetworkX for path computation.

        Args:
            from_id: Starting node id.
            to_id: Target node id.

        Returns:
            List of node ids along the path, or None if no path exists.
        """
        with self._db._lock:
            conn = self._db.connect()
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

    def blast_radius(
        self,
        node_id: str,
        depth: int = 3,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Node], int]:
        """Return paginated callers up to ``depth`` hops via recursive CTE.

        Two-pass: IDs-only CTE first (no joins), then full rows for slice only.

        Returns:
            (nodes_slice, total_count)
        """
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        with self._db._lock:
            conn = self._db.connect()
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

    def build_blast_radius_payload(
        self,
        node_id: str,
        depth: int = 3,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Build a structured blast-radius payload dict.

        Args:
            node_id: Root node id.
            depth: Max hop depth.
            limit: Page size.
            offset: Page offset.

        Returns:
            Dict with node_id, depth, count, total, truncated, nodes, etc.
        """
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        nodes, total = self.blast_radius(node_id, depth=depth, limit=limit, offset=offset)
        truncated = total > offset + limit
        next_offset = offset + limit if truncated else None
        return {
            "node_id": node_id,
            "depth": depth,
            "count": len(nodes),
            "total": total,
            "truncated": truncated,
            "depth_reached": depth,
            "next_offset": next_offset,
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "path": n.path,
                    "kind": n.kind.value,
                    "depth": getattr(n, "depth", None) or 0,
                    "summary": n.summary,
                }
                for n in nodes
            ],
        }

    def god_nodes(self, limit: int = 10) -> list[dict]:
        """Return nodes with highest in-degree (most callers).

        Args:
            limit: Maximum number of nodes to return.

        Returns:
            List of dicts with node info and in-degree count.
        """
        with self._db._lock:
            conn = self._db.connect()
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
            return [
                {
                    "node": row_to_node(r),
                    "in_degree": r["_indeg"],
                }
                for r in rows
            ]

    def stats(self) -> dict[str, Any]:
        """Return node/edge counts broken down by kind.

        Returns:
            Dict with total_nodes, total_edges, nodes_by_kind, edges_by_kind.
        """
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
                "total_nodes": n_total,
                "total_edges": e_total,
                "nodes_by_kind": by_kind,
                "edges_by_kind": by_edge,
            }

    def community_members(self, community_id: str) -> list[Node]:
        """Return all nodes belonging to a community.

        Args:
            community_id: Community identifier.

        Returns:
            List of active nodes in the community.
        """
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT * FROM nodes WHERE community_id = ? AND deleted_at IS NULL",
                (community_id,),
            ).fetchall()
            return [row_to_node(r) for r in rows]
