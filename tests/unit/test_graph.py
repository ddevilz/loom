from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.edge import Edge, EdgeType
from loom.core.graph import LoomGraph
from loom.core.node import Node, NodeKind, NodeSource


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
    g = LoomGraph(db_path=tmp_path / "loom.db")
    a = _fn("a.py", "f")
    b = _fn("b.py", "g")
    await g.bulk_upsert_nodes([a, b])
    got = await g.get_node(a.id)
    assert got is not None
    assert got.name == "f"


@pytest.mark.asyncio
async def test_bulk_upsert_edges_and_callers(tmp_path: Path):
    g = LoomGraph(db_path=tmp_path / "loom.db")
    a = _fn("a.py", "f")
    b = _fn("b.py", "g")
    await g.bulk_upsert_nodes([a, b])
    await g.bulk_upsert_edges([
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    rows = await g.neighbors(b.id, depth=1, edge_types=[EdgeType.CALLS])
    assert any(n.id == a.id for n in rows)


@pytest.mark.asyncio
async def test_blast_radius_transitive(tmp_path: Path):
    g = LoomGraph(db_path=tmp_path / "loom.db")
    a, b, c = _fn("a.py", "f"), _fn("b.py", "g"), _fn("c.py", "h")
    await g.bulk_upsert_nodes([a, b, c])
    # a -> b -> c  (a calls b, b calls c)
    await g.bulk_upsert_edges([
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS),
        Edge(from_id=b.id, to_id=c.id, kind=EdgeType.CALLS),
    ])
    result = await g.blast_radius(c.id, depth=3)
    ids = {n.id for n in result}
    assert a.id in ids and b.id in ids


@pytest.mark.asyncio
async def test_replace_file_atomic(tmp_path: Path):
    g = LoomGraph(db_path=tmp_path / "loom.db")
    old = _fn("a.py", "old")
    await g.bulk_upsert_nodes([old])
    new = _fn("a.py", "new")
    await g.replace_file("a.py", [new], [])
    assert await g.get_node(old.id) is None
    assert await g.get_node(new.id) is not None


@pytest.mark.asyncio
async def test_get_content_hashes(tmp_path: Path):
    g = LoomGraph(db_path=tmp_path / "loom.db")
    a = _fn("a.py", "f")
    await g.bulk_upsert_nodes([a])
    hashes = await g.get_content_hashes()
    assert hashes.get("a.py") == "hash-a.py"


@pytest.mark.asyncio
async def test_neighbors_direction_in(tmp_path: Path):
    g = LoomGraph(db_path=tmp_path / "loom.db")
    a, b = _fn("a.py", "caller"), _fn("b.py", "callee")
    await g.bulk_upsert_nodes([a, b])
    await g.bulk_upsert_edges([
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    callers_of_b = await g.neighbors(
        b.id, depth=1, edge_types=[EdgeType.CALLS], direction="in"
    )
    assert {n.id for n in callers_of_b} == {a.id}
    callees_of_a = await g.neighbors(
        a.id, depth=1, edge_types=[EdgeType.CALLS], direction="out"
    )
    assert {n.id for n in callees_of_a} == {b.id}
    # reverse must be empty
    callers_of_a = await g.neighbors(
        a.id, depth=1, edge_types=[EdgeType.CALLS], direction="in"
    )
    assert callers_of_a == []
