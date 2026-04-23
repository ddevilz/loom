<<<<<<< HEAD
from __future__ import annotations

from pathlib import Path
=======
import json
import socket
>>>>>>> main

import pytest

from loom.analysis.communities import compute_communities
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
<<<<<<< HEAD
=======
from loom.core.falkor import cypher
>>>>>>> main


def _func(name: str, path: str, line: int) -> Node:
    return Node(
        id=f"function:{path}:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        start_line=line,
        end_line=line + 3,
        language="python",
        metadata={},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_communities_creates_community_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

<<<<<<< HEAD
    auth_names = ["login", "logout", "validate", "refresh"]
    data_names = ["fetch", "store", "delete", "update"]
    auth_nodes = [_func(f"auth_{n}", "src/auth.py", 10 + i * 5) for i, n in enumerate(auth_names)]
    data_nodes = [_func(f"data_{n}", "src/data.py", 20 + i * 5) for i, n in enumerate(data_names)]
=======
    g = LoomGraph(graph_name="loom_pytest_communities")
    await g.query(cypher.CLEAR_GRAPH)
>>>>>>> main

    await g.bulk_upsert_nodes(auth_nodes + data_nodes)

    auth_edges = [
        Edge(from_id=auth_nodes[0].id, to_id=auth_nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=auth_nodes[1].id, to_id=auth_nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=auth_nodes[2].id, to_id=auth_nodes[3].id, kind=EdgeType.CALLS),
        Edge(from_id=auth_nodes[3].id, to_id=auth_nodes[0].id, kind=EdgeType.CALLS),
    ]
    data_edges = [
        Edge(from_id=data_nodes[0].id, to_id=data_nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=data_nodes[1].id, to_id=data_nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=data_nodes[2].id, to_id=data_nodes[3].id, kind=EdgeType.CALLS),
        Edge(from_id=data_nodes[3].id, to_id=data_nodes[0].id, kind=EdgeType.CALLS),
    ]
    # Sparse cross-cluster edge
    cross_edge = Edge(from_id=auth_nodes[0].id, to_id=data_nodes[0].id, kind=EdgeType.CALLS)

    await g.bulk_upsert_edges(auth_edges + data_edges + [cross_edge])

    count = await compute_communities(g)
    assert count >= 1, "Should detect at least 1 community"

    # Verify community nodes were created
    members = await g.community_members(await _first_community_id(g))
    assert len(members) >= 2

<<<<<<< HEAD
    # Verify community_id set on function nodes
    sample = await g.get_node(auth_nodes[0].id)
    assert sample is not None
    assert sample.community_id is not None
=======
    # Verify results
    assert len(node_to_community) >= 6, (
        "Should cluster at least 6 nodes (2 communities × 3 min)"
    )
>>>>>>> main


<<<<<<< HEAD
async def _first_community_id(g: LoomGraph) -> str:
    def _run() -> str:
        with g._lock:
            conn = g._connect()
            row = conn.execute(
                "SELECT id FROM nodes WHERE kind = 'community' LIMIT 1"
            ).fetchone()
            return row["id"] if row else ""
    import asyncio
    return await asyncio.to_thread(_run)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_communities_handles_empty_graph(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    count = await compute_communities(g)
    assert count == 0
=======
    # Verify community names are semantic
    community_names = {c["name"] for c in communities}
    assert any(name in community_names for name in ["auth", "data"]), (
        f"Community names should be semantic, got: {community_names}"
    )

    # Verify MEMBER_OF edges exist
    member_of_query = """
    MATCH (f)-[r:MEMBER_OF]->(c:Community)
    RETURN count(r) AS count
    """
    member_count = await g.query(member_of_query)
    assert member_count[0]["count"] >= 6, (
        "Should have MEMBER_OF edges for clustered nodes"
    )

    # Verify community_id is set on function nodes
    for node_id in list(node_to_community.keys())[:3]:
        node = await g.get_node(node_id)
        assert node is not None
        assert node.community_id is not None, (
            f"Node {node_id} should have community_id set"
        )
        assert node.community_id == node_to_community[node_id]

    # Verify modularity metadata
    for comm in communities:
        raw_metadata = comm["metadata"]
        metadata = (
            json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        )
        assert "modularity" in metadata
        assert "member_count" in metadata
        assert metadata["member_count"] >= 3


@pytest.mark.integration
async def test_detect_communities_filters_small_communities():
    """Test that communities with < 3 members are filtered out."""
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_small_communities")
    await g.query(cypher.CLEAR_GRAPH)

    # Create a small graph with only 2 connected nodes
    nodes = [
        Node(
            id=f"function:src/small.py:func{i}:10",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"func{i}",
            path="src/small.py",
            start_line=10 + i * 5,
            end_line=10 + i * 5 + 3,
            language="python",
            metadata={},
        )
        for i in range(2)
    ]

    await g.bulk_create_nodes(nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_create_edges(edges)

    # Run community detection
    node_to_community = await detect_communities(g)

    # Should return empty because community has < 3 members
    assert len(node_to_community) == 0, (
        "Should not cluster communities with < 3 members"
    )

    # Verify no community nodes created
    community_query = "MATCH (c:Community) RETURN count(c) AS count"
    result = await g.query(community_query)
    assert result[0]["count"] == 0


@pytest.mark.integration
async def test_detect_communities_handles_empty_graph():
    """Test that community detection handles empty graphs gracefully."""
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_empty")
    await g.query(cypher.CLEAR_GRAPH)

    # Run on empty graph
    node_to_community = await detect_communities(g)

    assert len(node_to_community) == 0
>>>>>>> main
