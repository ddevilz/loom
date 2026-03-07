"""Integration tests for EdgeType storage consistency via EdgeTypeAdapter."""

from __future__ import annotations

import pytest

from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter


@pytest.mark.asyncio
async def test_edge_persists_with_uppercase_relationship_type():
    """Verify edges are stored with uppercase relationship types in FalkorDB."""
    graph = LoomGraph(graph_name="test_edge_storage")
    
    # Create test nodes
    node_a = Node(
        id="function:test:func_a",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="func_a",
        path="test.py",
        metadata={},
    )
    node_b = Node(
        id="function:test:func_b",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="func_b",
        path="test.py",
        metadata={},
    )
    
    await graph.bulk_create_nodes([node_a, node_b])
    
    # Create edge with domain EdgeType
    edge = Edge(
        from_id=node_a.id,
        to_id=node_b.id,
        kind=EdgeType.CALLS,
        confidence=0.9,
        metadata={},
    )
    
    await graph.bulk_create_edges([edge])
    
    # Query using uppercase relationship type (storage format)
    calls_rel = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
    rows = await graph.query(
        f"MATCH (a)-[r:{calls_rel}]->(b) WHERE a.id = $from_id AND b.id = $to_id RETURN type(r) AS rel_type, r.confidence AS confidence",
        {"from_id": node_a.id, "to_id": node_b.id},
    )
    
    assert len(rows) == 1
    assert rows[0]["rel_type"] == "CALLS"  # Stored as uppercase
    assert rows[0]["confidence"] == 0.9
    
    # Cleanup
    await graph.query("MATCH (n) WHERE n.id IN [$id1, $id2] DETACH DELETE n", {"id1": node_a.id, "id2": node_b.id})


@pytest.mark.asyncio
async def test_edge_query_with_domain_edge_type():
    """Verify queries work when using domain EdgeType with adapter."""
    graph = LoomGraph(graph_name="test_edge_storage")
    
    # Create test nodes
    node_a = Node(
        id="function:test:import_a",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="import_a",
        path="test.py",
        metadata={},
    )
    node_b = Node(
        id="module:test:module_b",
        kind=NodeKind.MODULE,
        source=NodeSource.CODE,
        name="module_b",
        path="test.py",
        metadata={},
    )
    
    await graph.bulk_create_nodes([node_a, node_b])
    
    # Create IMPORTS edge
    edge = Edge(
        from_id=node_a.id,
        to_id=node_b.id,
        kind=EdgeType.IMPORTS,
        confidence=1.0,
        metadata={},
    )
    
    await graph.bulk_create_edges([edge])
    
    # Query using adapter to convert domain type to storage format
    imports_rel = EdgeTypeAdapter.to_storage(EdgeType.IMPORTS)
    rows = await graph.query(
        f"MATCH (a)-[:{imports_rel}]->(b) WHERE a.id = $from_id RETURN b.id AS to_id",
        {"from_id": node_a.id},
    )
    
    assert len(rows) == 1
    assert rows[0]["to_id"] == node_b.id
    
    # Cleanup
    await graph.query("MATCH (n) WHERE n.id IN [$id1, $id2] DETACH DELETE n", {"id1": node_a.id, "id2": node_b.id})


@pytest.mark.asyncio
async def test_multiple_edge_types_persist_correctly():
    """Verify multiple edge types can coexist with correct storage format."""
    graph = LoomGraph(graph_name="test_edge_storage")
    
    # Create test nodes
    func_node = Node(
        id="function:test:multi_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="multi_func",
        path="test.py",
        metadata={},
    )
    doc_node = Node(
        id="doc:test:ticket",
        kind=NodeKind.DOCUMENT,
        source=NodeSource.DOC,
        name="TEST-123",
        path="jira://TEST-123",
        metadata={},
    )
    other_func = Node(
        id="function:test:other_func",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="other_func",
        path="test.py",
        metadata={},
    )
    
    await graph.bulk_create_nodes([func_node, doc_node, other_func])
    
    # Create edges of different types
    edges = [
        Edge(from_id=func_node.id, to_id=doc_node.id, kind=EdgeType.LOOM_IMPLEMENTS, confidence=0.95, metadata={}),
        Edge(from_id=func_node.id, to_id=other_func.id, kind=EdgeType.CALLS, confidence=0.85, metadata={}),
    ]
    
    await graph.bulk_create_edges(edges)
    
    # Query all relationship types
    rows = await graph.query(
        "MATCH (a {id: $id})-[r]->(b) RETURN type(r) AS rel_type, b.id AS to_id ORDER BY rel_type",
        {"id": func_node.id},
    )
    
    assert len(rows) == 2
    # Relationship types should be uppercase (storage format)
    rel_types = [row["rel_type"] for row in rows]
    assert "CALLS" in rel_types
    assert "LOOM_IMPLEMENTS" in rel_types
    
    # Cleanup
    await graph.query(
        "MATCH (n) WHERE n.id IN [$id1, $id2, $id3] DETACH DELETE n",
        {"id1": func_node.id, "id2": doc_node.id, "id3": other_func.id},
    )


@pytest.mark.asyncio
async def test_edge_type_value_does_not_match_storage():
    """Verify that EdgeType.value (lowercase) does NOT match stored edges."""
    graph = LoomGraph(graph_name="test_edge_storage")
    
    # Create test nodes
    node_a = Node(
        id="function:test:value_test_a",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="value_test_a",
        path="test.py",
        metadata={},
    )
    node_b = Node(
        id="function:test:value_test_b",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="value_test_b",
        path="test.py",
        metadata={},
    )
    
    await graph.bulk_create_nodes([node_a, node_b])
    
    # Create CALLS edge
    edge = Edge(
        from_id=node_a.id,
        to_id=node_b.id,
        kind=EdgeType.CALLS,
        confidence=0.9,
        metadata={},
    )
    
    await graph.bulk_create_edges([edge])
    
    # Query using lowercase value (WRONG - should not match)
    lowercase_value = EdgeType.CALLS.value  # "calls"
    rows = await graph.query(
        f"MATCH (a)-[:{lowercase_value}]->(b) WHERE a.id = $from_id RETURN b.id AS to_id",
        {"from_id": node_a.id},
    )
    
    # Should return ZERO results because "calls" != "CALLS" in storage
    assert len(rows) == 0
    
    # Query using uppercase name via adapter (CORRECT - should match)
    uppercase_name = EdgeTypeAdapter.to_storage(EdgeType.CALLS)  # "CALLS"
    rows = await graph.query(
        f"MATCH (a)-[:{uppercase_name}]->(b) WHERE a.id = $from_id RETURN b.id AS to_id",
        {"from_id": node_a.id},
    )
    
    # Should return ONE result
    assert len(rows) == 1
    assert rows[0]["to_id"] == node_b.id
    
    # Cleanup
    await graph.query("MATCH (n) WHERE n.id IN [$id1, $id2] DETACH DELETE n", {"id1": node_a.id, "id2": node_b.id})
