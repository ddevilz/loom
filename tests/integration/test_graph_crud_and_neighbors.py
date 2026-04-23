from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
<<<<<<< HEAD


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_bulk_and_query_roundtrip(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
=======
from loom.core.falkor import cypher


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
async def test_graph_bulk_and_query_roundtrip():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest")
    await g.query(cypher.CLEAR_GRAPH)
>>>>>>> main

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

    await g.bulk_upsert_nodes(nodes)

    edges = [
        Edge(
            from_id=nodes[i].id,
            to_id=nodes[i + 1].id,
            kind=EdgeType.CALLS,
        )
        for i in range(5)
    ]

    await g.bulk_upsert_edges(edges)

<<<<<<< HEAD
    stats = await g.stats()
    assert stats["nodes"] == 10
    assert stats["edges"] == 5
=======
    labeled = await g.query("MATCH (n:Function) RETURN count(n) AS c")
    assert labeled[0]["c"] == 10

    count_rows = await g.query(cypher.COUNT_NODES)
    assert count_rows[0]["c"] == 10
>>>>>>> main

    n0 = await g.get_node(nodes[0].id)
    assert n0 is not None
    assert n0.id == nodes[0].id
    assert n0.name == "f0"

    # depth=2 neighbors from f0 via CALLS: f1 (depth 1) and f2 (depth 2)
    neigh = await g.neighbors(nodes[0].id, depth=2, edge_types=[EdgeType.CALLS])
    neigh_ids = {n.id for n in neigh}
    assert nodes[1].id in neigh_ids
    assert nodes[2].id in neigh_ids
    # f6 is not reachable via CALLS from f0 within depth 2
    assert nodes[6].id not in neigh_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upsert_is_idempotent(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    node = Node(
        id="function:src/mod.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="src/mod.py",
        language="python",
        metadata={},
    )

    await g.bulk_upsert_nodes([node])
    await g.bulk_upsert_nodes([node])  # second upsert — no duplicate

    stats = await g.stats()
    assert stats["nodes"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_replace_file_atomic(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    old_node = Node(
        id="function:src/a.py:old_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="old_func",
        path="src/a.py",
        language="python",
        metadata={},
    )
    await g.bulk_upsert_nodes([old_node])

    new_node = Node(
        id="function:src/a.py:new_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="new_func",
        path="src/a.py",
        language="python",
        metadata={},
    )
    await g.replace_file("src/a.py", [new_node], [])

    stats = await g.stats()
    assert stats["nodes"] == 1  # old removed, new inserted

    n = await g.get_node("function:src/a.py:new_func")
    assert n is not None
    assert n.name == "new_func"

    gone = await g.get_node("function:src/a.py:old_func")
    assert gone is None
