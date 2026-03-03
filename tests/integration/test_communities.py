import socket
import json

import pytest

from loom.analysis.code.communities import detect_communities
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor import queries


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
async def test_detect_communities_creates_community_nodes():
    """Test that community detection creates COMMUNITY nodes and MEMBER_OF edges."""
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_communities")
    await g.query(queries.CLEAR_GRAPH)

    # Create two clusters of functions with interconnected calls
    # Cluster 1: auth functions
    auth_nodes = [
        Node(
            id=f"function:src/auth.py:auth_{name}:10",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"auth_{name}",
            path="src/auth.py",
            start_line=10 + i * 5,
            end_line=10 + i * 5 + 3,
            language="python",
            metadata={},
        )
        for i, name in enumerate(["login", "logout", "validate", "refresh"])
    ]

    # Cluster 2: data functions
    data_nodes = [
        Node(
            id=f"function:src/data.py:data_{name}:20",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"data_{name}",
            path="src/data.py",
            start_line=20 + i * 5,
            end_line=20 + i * 5 + 3,
            language="python",
            metadata={},
        )
        for i, name in enumerate(["fetch", "store", "delete", "update"])
    ]

    all_nodes = auth_nodes + data_nodes
    await g.bulk_create_nodes(all_nodes)

    # Create dense connections within each cluster
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

    # Sparse connection between clusters
    cross_edges = [
        Edge(from_id=auth_nodes[0].id, to_id=data_nodes[0].id, kind=EdgeType.CALLS),
    ]

    await g.bulk_create_edges(auth_edges + data_edges + cross_edges)

    # Run community detection
    node_to_community = await detect_communities(g)

    # Verify results
    assert len(node_to_community) >= 6, "Should cluster at least 6 nodes (2 communities × 3 min)"

    # Check that community nodes were created
    community_query = """
    MATCH (c:Community)
    RETURN c.id AS id, c.name AS name, c.metadata AS metadata
    """
    communities = await g.query(community_query)
    assert len(communities) >= 2, "Should detect at least 2 communities"

    # Verify community names are semantic
    community_names = {c["name"] for c in communities}
    assert any(name in community_names for name in ["auth", "data"]), \
        f"Community names should be semantic, got: {community_names}"

    # Verify MEMBER_OF edges exist
    member_of_query = """
    MATCH (f)-[r:MEMBER_OF]->(c:Community)
    RETURN count(r) AS count
    """
    member_count = await g.query(member_of_query)
    assert member_count[0]["count"] >= 6, "Should have MEMBER_OF edges for clustered nodes"

    # Verify community_id is set on function nodes
    for node_id in list(node_to_community.keys())[:3]:
        node = await g.get_node(node_id)
        assert node is not None
        assert node.community_id is not None, f"Node {node_id} should have community_id set"
        assert node.community_id == node_to_community[node_id]

    # Verify modularity metadata
    for comm in communities:
        raw_metadata = comm["metadata"]
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
        assert "modularity" in metadata
        assert "member_count" in metadata
        assert metadata["member_count"] >= 3


@pytest.mark.integration
async def test_detect_communities_filters_small_communities():
    """Test that communities with < 3 members are filtered out."""
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_small_communities")
    await g.query(queries.CLEAR_GRAPH)

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
    assert len(node_to_community) == 0, "Should not cluster communities with < 3 members"

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
    await g.query(queries.CLEAR_GRAPH)

    # Run on empty graph
    node_to_community = await detect_communities(g)

    assert len(node_to_community) == 0
