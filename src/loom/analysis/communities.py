from __future__ import annotations

import asyncio
import json
import time

import networkx as nx
import networkx.algorithms.community as nx_comm

from loom.core.context import DB
from loom.core.edge import EdgeType


async def compute_communities(db: DB) -> int:
    """Run Louvain on CALLS+COUPLED_WITH subgraph.

    Persists community_id on every member node and materializes one
    COMMUNITY-kind node per cluster. Returns the number of communities found.
    """

    def _run() -> int:
        with db._lock:
            conn = db.connect()
            edges = conn.execute(
                "SELECT from_id, to_id FROM edges WHERE kind IN (?, ?)",
                (EdgeType.CALLS.value, EdgeType.COUPLED_WITH.value),
            ).fetchall()
            g: nx.Graph = nx.Graph()
            for row in edges:
                g.add_edge(row["from_id"], row["to_id"])
            if g.number_of_nodes() == 0:
                return 0
            communities = nx_comm.louvain_communities(g, seed=42)
            now = int(time.time())
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM nodes WHERE kind = 'community'")
                conn.execute("UPDATE nodes SET community_id = NULL")
                for idx, members in enumerate(communities):
                    cid = f"community:{idx:04d}"
                    conn.execute(
                        """INSERT INTO nodes
                               (id, kind, source, name, path, metadata, updated_at)
                           VALUES (?, 'community', 'code', ?, '', ?, ?)""",
                        (cid, cid, json.dumps({"size": len(members)}), now),
                    )
                    member_ids = list(members)
                    if not member_ids:
                        continue
                    for i in range(0, len(member_ids), 900):
                        chunk = member_ids[i : i + 900]
                        ph = ",".join("?" * len(chunk))
                        conn.execute(
                            f"UPDATE nodes SET community_id = ? WHERE id IN ({ph})",
                            (cid, *chunk),
                        )
                conn.commit()
                return len(communities)
            except Exception:
                conn.rollback()
                raise

    return await asyncio.to_thread(_run)
