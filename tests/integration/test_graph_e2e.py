import socket
import sys
import time
from pathlib import Path

import pytest

from loom.core import LoomGraph
from loom.core.falkor import cypher

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fixtures.sample_graph import build_sample_graph


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
async def test_graph_e2e_foundation():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_e2e")
    await g.query(cypher.CLEAR_GRAPH)

    fixture = build_sample_graph()
    nodes = fixture["nodes"]
    edges = fixture["edges"]
    fid = fixture["function_ids"]

    await g.bulk_create_nodes(nodes)
    await g.bulk_create_edges(edges)

    # 15 function nodes + 2 doc sections
    count = (await g.query(cypher.COUNT_NODES))[0]["c"]
    assert count == 17

    # Blast radius (CALLS up to depth 3) from function x.
    blast_rows = await g.query(
        "MATCH (f:Function)-[:CALLS*1..3]->(g:Function) "
        "WHERE f.name=$name "
        "RETURN DISTINCT g.name AS name",
        params={"name": "x"},
    )
    blast = {r["name"] for r in blast_rows}
    assert blast == {"a", "b", "c", "d", "e", "f", "g", "h", "i", "k"}

    # Cross-domain links: validate_user IMPLEMENTS a spec section
    impl_rows = await g.query(
        "MATCH (f:Function)-[:IMPLEMENTS]->(s:Section) "
        "WHERE f.name=$name "
        "RETURN s.id AS id",
        params={"name": "validate_user"},
    )
    assert {r["id"] for r in impl_rows} == {"doc:spec.pdf:1.0"}

    # LoomGraph.neighbors should accept a plain function name and return depth-2 neighborhood.
    neigh = await g.neighbors("validate_user", depth=2)
    neigh_ids = {n.id for n in neigh}
    assert neigh_ids == {
        fid["parse_token"],
        fid["hash_pw"],
        fid["k"],
        "doc:spec.pdf:1.0",
        "doc:spec.pdf:2.0",
    }

    # Performance: bulk insert 100 nodes under 1 second
    await g.query(cypher.CLEAR_GRAPH)
    fixture2 = build_sample_graph()
    await g.bulk_create_nodes(fixture2["nodes"])
    await g.bulk_create_edges(fixture2["edges"])

    # Add 100 extra function nodes
    from loom.core import Node, NodeKind, NodeSource

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
    await g.bulk_create_nodes(extra_nodes)
    dt = time.perf_counter() - t0
    assert dt < 1.0
