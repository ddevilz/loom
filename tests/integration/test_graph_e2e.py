from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from loom.core.context import DB
from loom.core.node import Node, NodeKind, NodeSource
from loom.query import traversal
from loom.store import edges as edge_store
from loom.store import nodes as node_store

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fixtures.sample_graph import build_sample_graph


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_e2e_foundation(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    fixture = build_sample_graph()
    nodes = fixture["nodes"]
    edges = fixture["edges"]
    fid = fixture["function_ids"]

    await node_store.bulk_upsert_nodes(db, nodes)
    await edge_store.bulk_upsert_edges(db, edges)

    s = await traversal.stats(db)
    assert s["nodes"] == 15

    blast = await traversal.blast_radius(db, fid["x"], depth=3)
    assert isinstance(blast, list)

    callers_k = await traversal.neighbors(db, fid["k"], depth=1, edge_types=None, direction="in")
    caller_names = {n.name for n in callers_k}
    assert "d" in caller_names
    assert "parse_token" in caller_names
    assert "hash_pw" in caller_names

    callees_x = await traversal.neighbors(db, fid["x"], depth=2, direction="out")
    callee_names = {n.name for n in callees_x}
    assert {"a", "b", "c"}.issubset(callee_names)
    assert {"d", "e", "f", "g", "h"}.issubset(callee_names)

    node = await node_store.get_node(db, fid["validate_user"])
    assert node is not None
    assert node.name == "validate_user"

    neigh = await traversal.neighbors(db, fid["validate_user"], depth=2)
    neigh_names = {n.name for n in neigh}
    assert "parse_token" in neigh_names
    assert "hash_pw" in neigh_names
    assert "k" in neigh_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_insert_performance(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "bench.db")

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
    await node_store.bulk_upsert_nodes(db, extra_nodes)
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"bulk insert 100 nodes took {dt:.2f}s"
