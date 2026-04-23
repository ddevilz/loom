from __future__ import annotations

import pytest
from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.store import edges as edge_store
from loom.store import nodes as node_store
from loom.query import traversal


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
async def db_with_graph() -> DB:
    db = DB(path=":memory:")
    a, b, c = _fn("a.py", "f"), _fn("b.py", "g"), _fn("c.py", "h")
    await node_store.bulk_upsert_nodes(db, [a, b, c])
    # a calls b, b calls c
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS),
        Edge(from_id=b.id, to_id=c.id, kind=EdgeType.CALLS),
    ])
    return db


@pytest.mark.asyncio
async def test_neighbors_in(db_with_graph: DB) -> None:
    db = db_with_graph
    nodes = await traversal.neighbors(db, _fn("b.py", "g").id, depth=1,
                                       edge_types=[EdgeType.CALLS], direction="in")
    assert len(nodes) == 1
    assert nodes[0].name == "f"


@pytest.mark.asyncio
async def test_neighbors_out(db_with_graph: DB) -> None:
    db = db_with_graph
    nodes = await traversal.neighbors(db, _fn("a.py", "f").id, depth=1,
                                       edge_types=[EdgeType.CALLS], direction="out")
    assert len(nodes) == 1
    assert nodes[0].name == "g"


@pytest.mark.asyncio
async def test_blast_radius(db_with_graph: DB) -> None:
    db = db_with_graph
    # c is called by b which is called by a — blast radius of c = [b, a]
    results = await traversal.blast_radius(db, _fn("c.py", "h").id, depth=3)
    names = {n.name for n in results}
    assert "g" in names
    assert "f" in names


@pytest.mark.asyncio
async def test_shortest_path(db_with_graph: DB) -> None:
    db = db_with_graph
    path = await traversal.shortest_path(
        db, _fn("a.py", "f").id, _fn("c.py", "h").id
    )
    assert path is not None
    assert [n.name for n in path] == ["f", "g", "h"]


@pytest.mark.asyncio
async def test_shortest_path_none_when_unreachable(db_with_graph: DB) -> None:
    db = db_with_graph
    path = await traversal.shortest_path(
        db, _fn("c.py", "h").id, _fn("a.py", "f").id
    )
    assert path is None


@pytest.mark.asyncio
async def test_god_nodes(db_with_graph: DB) -> None:
    db = db_with_graph
    pairs = await traversal.god_nodes(db, limit=10)
    assert len(pairs) > 0
    # c.h has 1 incoming call, b.g has 1 — both should appear
    names = {n.name for n, _ in pairs}
    assert "h" in names


@pytest.mark.asyncio
async def test_stats(db_with_graph: DB) -> None:
    db = db_with_graph
    s = await traversal.stats(db)
    assert s["nodes"] == 3
    assert s["edges"] == 2
