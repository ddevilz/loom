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
def test_node_merge_is_idempotent_and_updates_properties():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_merge")
    g.query(queries.CLEAR_GRAPH)

    n1 = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
        language="python",
        metadata={"v": 1},
    )
    g.create_node(n1)

    n1b = Node(
        id=n1.id,
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f_renamed",
        path="src/x.py",
        language="python",
        metadata={"v": 2, "nested": {"k": "x"}},
    )
    g.create_node(n1b)

    count = g.query(queries.COUNT_NODES)[0]["c"]
    assert count == 1

    loaded = g.get_node(n1.id)
    assert loaded is not None
    assert loaded.name == "f_renamed"
    assert loaded.metadata.get("v") == 2
    assert loaded.metadata.get("nested", {}).get("k") == "x"


@pytest.mark.integration
def test_bulk_edges_mixed_types_and_neighbor_filtering():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_edges")
    g.query(queries.CLEAR_GRAPH)

    nodes = [
        Node(
            id=f"function:src/m.py:f{i}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"f{i}",
            path="src/m.py",
            language="python",
            metadata={},
        )
        for i in range(4)
    ]
    g.bulk_create_nodes(nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[0].id, to_id=nodes[2].id, kind=EdgeType.IMPORTS),
        Edge(
            from_id=nodes[1].id,
            to_id="doc:spec.pdf:1.0",
            kind=EdgeType.LOOM_SPECIFIES,
            confidence=0.4,
            link_method="name_match",
            link_reason="matched section heading",
            metadata={"score": 0.4},
        ),
    ]

    g.create_node(
        Node(
            id="doc:spec.pdf:1.0",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="1.0",
            path="spec.pdf",
            metadata={},
        )
    )

    g.bulk_create_edges(edges)

    rel_count = g.query("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    assert rel_count == 3

    calls_only = g.neighbors(nodes[0].id, depth=1, edge_types=[EdgeType.CALLS])
    calls_ids = {n.id for n in calls_only}
    assert nodes[1].id in calls_ids
    assert nodes[2].id not in calls_ids

    all_neighbors = g.neighbors(nodes[0].id, depth=1, edge_types=[EdgeType.CALLS, EdgeType.IMPORTS])
    all_ids = {n.id for n in all_neighbors}
    assert nodes[1].id in all_ids
    assert nodes[2].id in all_ids


@pytest.mark.integration
def test_loom_edge_properties_persisted():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_loomedge")
    g.query(queries.CLEAR_GRAPH)

    code = Node(
        id="function:src/a.py:fa",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="fa",
        path="src/a.py",
        language="python",
        metadata={},
    )
    doc = Node(
        id="doc:spec.pdf:2.0",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="2.0",
        path="spec.pdf",
        metadata={},
    )
    g.bulk_create_nodes([code, doc])

    e = Edge(
        from_id=code.id,
        to_id=doc.id,
        kind=EdgeType.LOOM_IMPLEMENTS,
        confidence=0.55,
        link_method="llm_match",
        link_reason="LLM judged alignment",
        metadata={"model": "test"},
    )
    g.create_edge(e)

    rows = g.query(
        "MATCH (:Node {id: $a})-[r:LOOM_IMPLEMENTS]->(:Node {id: $b}) RETURN properties(r) AS props",
        params={"a": code.id, "b": doc.id},
    )
    assert rows
    props = rows[0]["props"]
    assert props.get("confidence") == pytest.approx(0.55)
    assert props.get("link_method") == "llm_match"
    assert props.get("link_reason")
    assert isinstance(props.get("metadata"), str)
