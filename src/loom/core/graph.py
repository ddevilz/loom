from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from loom.core.context import DB
from loom.core.edge import ConfidenceTier, Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.query import traversal as _traversal
from loom.query.search import search as _search
from loom.store import edges as _edge_store
from loom.store import nodes as _node_store

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

    async def update_summary(self, node_id: str, summary: str) -> bool:
        return await _node_store.update_summary(self._db, node_id, summary)

    async def blast_radius(self, node_id: str, depth: int = 3) -> list[Node]:
        return await _traversal.blast_radius(self._db, node_id, depth=depth)

    async def neighbors(
        self, node_id: str, depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        direction: str = "both",
    ) -> list[Node]:
        return await _traversal.neighbors(
            self._db, node_id, depth=depth,
            edge_types=edge_types, direction=direction,
        )

    async def shortest_path(self, from_id: str, to_id: str) -> list[Node] | None:
        return await _traversal.shortest_path(self._db, from_id, to_id)

    async def community_members(self, community_id: str) -> list[Node]:
        return await _traversal.community_members(self._db, community_id)

    async def god_nodes(self, limit: int = 20) -> list[tuple[Node, int]]:
        return await _traversal.god_nodes(self._db, limit)

    async def search(self, query: str, limit: int = 10) -> list[Node]:
        results = await _search(query, self._db, limit=limit)
        return [r.node for r in results]

    async def stats(self) -> dict[str, Any]:
        return await _traversal.stats(self._db)
