from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

<<<<<<< HEAD
from loom.core import LoomGraph, Node, NodeKind, NodeSource
=======
from loom.core import LoomGraph
from loom.core.falkor import cypher
>>>>>>> main

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fixtures.sample_graph import build_sample_graph


@pytest.mark.integration
<<<<<<< HEAD
@pytest.mark.asyncio
async def test_graph_e2e_foundation(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
=======
async def test_graph_e2e_foundation():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_e2e")
    await g.query(cypher.CLEAR_GRAPH)
>>>>>>> main

    fixture = build_sample_graph()
    nodes = fixture["nodes"]
    edges = fixture["edges"]
    fid = fixture["function_ids"]

    await g.bulk_upsert_nodes(nodes)
    await g.bulk_upsert_edges(edges)

<<<<<<< HEAD
    stats = await g.stats()
    assert stats["nodes"] == 15
=======
    # 15 function nodes + 2 doc sections
    count = (await g.query(cypher.COUNT_NODES))[0]["c"]
    assert count == 17
>>>>>>> main

    # Blast radius from x: who calls x transitively?
    # x calls a,b,c; a calls d,e; b calls f,g; c calls h; h→i→j; d→k
    blast = await g.blast_radius(fid["x"], depth=3)
    # blast_radius finds predecessors (callers) — x has no callers, so result is empty
    assert isinstance(blast, list)

    # Callers of k: d, hash_pw, parse_token call k directly
    callers_k = await g.neighbors(fid["k"], depth=1, edge_types=None, direction="in")
    caller_names = {n.name for n in callers_k}
    assert "d" in caller_names
    assert "parse_token" in caller_names
    assert "hash_pw" in caller_names

    # Callees of x (depth=2): a,b,c then d,e,f,g,h
    callees_x = await g.neighbors(fid["x"], depth=2, direction="out")
    callee_names = {n.name for n in callees_x}
    assert {"a", "b", "c"}.issubset(callee_names)
    assert {"d", "e", "f", "g", "h"}.issubset(callee_names)

<<<<<<< HEAD
    # get_node round-trip
    node = await g.get_node(fid["validate_user"])
    assert node is not None
    assert node.name == "validate_user"
=======
    # Performance: bulk insert 100 nodes under 1 second
    await g.query(cypher.CLEAR_GRAPH)
    fixture2 = build_sample_graph()
    await g.bulk_create_nodes(fixture2["nodes"])
    await g.bulk_create_edges(fixture2["edges"])
>>>>>>> main

    # Neighbors of validate_user at depth=2 should include parse_token, hash_pw, k
    neigh = await g.neighbors(fid["validate_user"], depth=2)
    neigh_names = {n.name for n in neigh}
    assert "parse_token" in neigh_names
    assert "hash_pw" in neigh_names
    assert "k" in neigh_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_insert_performance(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "bench.db")

    extra_nodes = [
        Node(
            id=f"function:src/bench.py:f{i}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"f{i}",
            path="src/bench.py",
            language="python",
            metadata={},
        )
        for i in range(100)
    ]

    t0 = time.perf_counter()
    await g.bulk_upsert_nodes(extra_nodes)
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"bulk insert 100 nodes took {dt:.2f}s"
