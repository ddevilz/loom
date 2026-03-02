import socket

import pytest

from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor import queries


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
def test_graph_bulk_and_query_roundtrip():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest")
    g.query(queries.CLEAR_GRAPH)

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

    g.bulk_create_nodes(nodes)

    edges = [
        Edge(
            from_id=nodes[i].id,
            to_id=nodes[i + 1].id,
            kind=EdgeType.CALLS,
        )
        for i in range(5)
    ]

    g.bulk_create_edges(edges)

    count_rows = g.query(queries.COUNT_NODES)
    assert count_rows[0]["c"] == 10

    n0 = g.get_node(nodes[0].id)
    assert n0 is not None
    assert n0.id == nodes[0].id

    neigh = g.neighbors(nodes[0].id, depth=2, edge_types=[EdgeType.CALLS])
    neigh_ids = {n.id for n in neigh}
    assert nodes[1].id in neigh_ids
    assert nodes[2].id in neigh_ids
