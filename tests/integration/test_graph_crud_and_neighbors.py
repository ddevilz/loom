from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.query import traversal
from loom.store import edges as edge_store
from loom.store import nodes as node_store


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_bulk_and_query_roundtrip(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    nodes = [
        Node(
            id=f"function:src/mod.py:f{i}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"f{i}",
            path="src/mod.py",
            start_line=i,
            end_line=i,
            language="python",
            metadata={},
        )
        for i in range(10)
    ]

    await node_store.bulk_upsert_nodes(db, nodes)

    edges = [
        Edge(
            from_id=nodes[i].id,
            to_id=nodes[i + 1].id,
            kind=EdgeType.CALLS,
        )
        for i in range(5)
    ]

    await edge_store.bulk_upsert_edges(db, edges)

    s = await traversal.stats(db)
    assert s["nodes"] == 10
    assert s["edges"] == 5

    n0 = await node_store.get_node(db, nodes[0].id)
    assert n0 is not None
    assert n0.id == nodes[0].id
    assert n0.name == "f0"

    neigh = await traversal.neighbors(db, nodes[0].id, depth=2, edge_types=[EdgeType.CALLS])
    neigh_ids = {n.id for n in neigh}
    assert nodes[1].id in neigh_ids
    assert nodes[2].id in neigh_ids
    assert nodes[6].id not in neigh_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_is_idempotent(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    node = Node(
        id="function:src/mod.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="src/mod.py",
        language="python",
        metadata={},
    )

    await node_store.bulk_upsert_nodes(db, [node])
    await node_store.bulk_upsert_nodes(db, [node])

    s = await traversal.stats(db)
    assert s["nodes"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replace_file_atomic(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    old_node = Node(
        id="function:src/a.py:old_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="old_func",
        path="src/a.py",
        language="python",
        metadata={},
    )
    await node_store.bulk_upsert_nodes(db, [old_node])

    new_node = Node(
        id="function:src/a.py:new_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="new_func",
        path="src/a.py",
        language="python",
        metadata={},
    )
    await node_store.replace_file(db, "src/a.py", [new_node], [])

    s = await traversal.stats(db)
    assert s["nodes"] == 1

    n = await node_store.get_node(db, "function:src/a.py:new_func")
    assert n is not None
    assert n.name == "new_func"

    gone = await node_store.get_node(db, "function:src/a.py:old_func")
    assert gone is None
