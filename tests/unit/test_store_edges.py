from __future__ import annotations

import asyncio

import pytest
from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.store import edges as edge_store
from loom.store import nodes as node_store


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash",
    )


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


@pytest.mark.asyncio
async def test_bulk_upsert_edges(db: DB) -> None:
    a, b = _fn("a.py", "f"), _fn("b.py", "g")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])

    def _check():
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT COUNT(*) as c FROM edges WHERE kind='calls'"
            ).fetchone()
            return row["c"]

    count = await asyncio.to_thread(_check)
    assert count == 1


@pytest.mark.asyncio
async def test_upsert_edges_idempotent(db: DB) -> None:
    a, b = _fn("a.py", "f"), _fn("b.py", "g")
    await node_store.bulk_upsert_nodes(db, [a, b])
    edge = Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    await edge_store.bulk_upsert_edges(db, [edge])
    await edge_store.bulk_upsert_edges(db, [edge])

    def _check():
        with db._lock:
            conn = db.connect()
            return conn.execute("SELECT COUNT(*) as c FROM edges").fetchone()["c"]

    count = await asyncio.to_thread(_check)
    assert count == 1
