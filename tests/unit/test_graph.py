from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.query import traversal
from loom.store import nodes as node_store
from loom.store import edges as edge_store


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash-" + path,
    )


@pytest.mark.asyncio
async def test_bulk_upsert_and_get(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    a = _fn("a.py", "f")
    b = _fn("b.py", "g")
    await node_store.bulk_upsert_nodes(db, [a, b])
    got = await node_store.get_node(db, a.id)
    assert got is not None
    assert got.name == "f"


@pytest.mark.asyncio
async def test_bulk_upsert_edges_and_callers(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    a = _fn("a.py", "f")
    b = _fn("b.py", "g")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    rows = await traversal.neighbors(db, b.id, depth=1, edge_types=[EdgeType.CALLS])
    assert any(n.id == a.id for n in rows)


@pytest.mark.asyncio
async def test_blast_radius_transitive(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    a, b, c = _fn("a.py", "f"), _fn("b.py", "g"), _fn("c.py", "h")
    await node_store.bulk_upsert_nodes(db, [a, b, c])
    # a -> b -> c  (a calls b, b calls c)
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS),
        Edge(from_id=b.id, to_id=c.id, kind=EdgeType.CALLS),
    ])
    result = await traversal.blast_radius(db, c.id, depth=3)
    ids = {n.id for n in result}
    assert a.id in ids and b.id in ids


@pytest.mark.asyncio
async def test_replace_file_atomic(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    old = _fn("a.py", "old")
    await node_store.bulk_upsert_nodes(db, [old])
    new = _fn("a.py", "new")
    await node_store.replace_file(db, "a.py", [new], [])
    assert await node_store.get_node(db, old.id) is None
    assert await node_store.get_node(db, new.id) is not None


@pytest.mark.asyncio
async def test_get_content_hashes(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    file_node = Node(
        id="file:a.py",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name="a.py",
        path="a.py",
        file_hash="hash-a.py",
        file_mtime=1234567890.0,
    )
    await node_store.bulk_upsert_nodes(db, [file_node])
    hashes = await node_store.get_content_hashes(db)
    entry = hashes.get("a.py")
    assert entry is not None
    assert entry[0] == "hash-a.py"
    assert entry[1] == 1234567890.0


@pytest.mark.asyncio
async def test_neighbors_direction_in(tmp_path: Path):
    db = DB(path=tmp_path / "loom.db")
    a, b = _fn("a.py", "caller"), _fn("b.py", "callee")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    callers_of_b = await traversal.neighbors(
        db, b.id, depth=1, edge_types=[EdgeType.CALLS], direction="in"
    )
    assert {n.id for n in callers_of_b} == {a.id}
    callees_of_a = await traversal.neighbors(
        db, a.id, depth=1, edge_types=[EdgeType.CALLS], direction="out"
    )
    assert {n.id for n in callees_of_a} == {b.id}
    callers_of_a = await traversal.neighbors(
        db, a.id, depth=1, edge_types=[EdgeType.CALLS], direction="in"
    )
    assert callers_of_a == []
