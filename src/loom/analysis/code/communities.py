from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import igraph as ig
import leidenalg

from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter

logger = logging.getLogger(__name__)


def _generate_community_name(member_names: list[str]) -> str:
    """Generate a semantic community name from member function names.
    
    Uses the most common word from function names split by underscore.
    E.g., auth_login, auth_logout, validate_auth → 'auth'
    """
    if not member_names:
        return "unnamed"
    
    words: list[str] = []
    for name in member_names:
        words.extend(name.split("_"))
    
    if not words:
        return member_names[0][:20]
    
    word_counts = Counter(words)
    most_common = word_counts.most_common(1)[0][0]
    
    return most_common


async def detect_communities(graph: LoomGraph) -> dict[str, str]:
    """Detect communities using Leiden algorithm and create community nodes.
    
    Args:
        graph: LoomGraph instance to analyze
    
    Returns:
        Dictionary mapping node_id → community_id for all clustered nodes
    
    Side effects:
        - Creates COMMUNITY nodes in the graph
        - Creates MEMBER_OF edges from functions to communities
        - Updates function nodes with community_id property
    """
    logger.info("Starting community detection with Leiden algorithm")
    
    # Query all function/method nodes and CALLS/IMPORTS edges
    query = """
    MATCH (n)
    WHERE n.kind IN ['function', 'method']
    RETURN n.id AS id, n.name AS name, n.kind AS kind
    """
    node_rows = await graph.query(query)
    
    if len(node_rows) < 3:
        logger.warning(f"Only {len(node_rows)} nodes found, skipping community detection")
        return {}
    
    # Build node index
    node_id_to_idx: dict[str, int] = {row["id"]: idx for idx, row in enumerate(node_rows)}
    idx_to_node_id: dict[int, str] = {idx: row["id"] for idx, row in enumerate(node_rows)}
    idx_to_name: dict[int, str] = {idx: row["name"] for idx, row in enumerate(node_rows)}
    
    # Query edges.
    # NOTE: edges are persisted with relationship *types* (e.g. :CALLS),
    # not via a r.kind property.
    calls_rel_type = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
    edge_query = f"""
    MATCH (a)-[r:{calls_rel_type}]->(b)
    WHERE a.kind IN ['function', 'method']
      AND b.kind IN ['function', 'method']
    RETURN a.id AS from_id, b.id AS to_id, r.confidence AS confidence
    """
    edge_rows = await graph.query(edge_query)

    # Build an undirected weighted graph for Leiden.
    # We collapse directed edges and multi-edges by summing weights.
    undirected_weight_by_pair: dict[tuple[int, int], float] = {}

    for edge_row in edge_rows:
        from_id = edge_row["from_id"]
        to_id = edge_row["to_id"]

        if from_id not in node_id_to_idx or to_id not in node_id_to_idx:
            continue

        a = node_id_to_idx[from_id]
        b = node_id_to_idx[to_id]
        i, j = (a, b) if a <= b else (b, a)

        confidence = edge_row.get("confidence")
        w = float(confidence) if confidence is not None else 1.0
        undirected_weight_by_pair[(i, j)] = undirected_weight_by_pair.get((i, j), 0.0) + w

    if not undirected_weight_by_pair:
        logger.warning("No edges found for community detection")
        return {}

    undirected_edges = list(undirected_weight_by_pair.keys())
    undirected_weights = [undirected_weight_by_pair[e] for e in undirected_edges]

    g_undirected = ig.Graph(n=len(node_rows), edges=undirected_edges, directed=False)
    g_undirected.es["weight"] = undirected_weights
    
    # Run Leiden algorithm
    logger.info(
        f"Running Leiden on graph with {g_undirected.vcount()} nodes and {g_undirected.ecount()} edges"
    )
    partition = leidenalg.find_partition(
        g_undirected,
        leidenalg.ModularityVertexPartition,
        weights=g_undirected.es["weight"],
    )
    
    modularity = partition.modularity
    logger.info(f"Community detection complete. Modularity: {modularity:.4f}")
    
    if modularity < 0.3:
        logger.warning(f"Low modularity ({modularity:.4f}) - clustering may not be meaningful")
        return {}
    
    # Group nodes by community
    communities: dict[int, list[int]] = {}
    for node_idx, community_id in enumerate(partition.membership):
        if community_id not in communities:
            communities[community_id] = []
        communities[community_id].append(node_idx)
    
    # Filter communities with < 3 members
    valid_communities = {
        comm_id: members
        for comm_id, members in communities.items()
        if len(members) >= 3
    }
    
    logger.info(
        f"Found {len(communities)} communities, "
        f"{len(valid_communities)} have >= 3 members"
    )
    
    # Create community nodes and edges
    node_to_community: dict[str, str] = {}
    community_nodes: list[Node] = []
    member_edges: list[Edge] = []
    
    for comm_id, member_indices in valid_communities.items():
        member_names = [idx_to_name[idx] for idx in member_indices]
        community_name = _generate_community_name(member_names)
        community_node_id = f"community:auto:{community_name}_{comm_id}"
        
        # Create community node
        community_node = Node(
            id=community_node_id,
            kind=NodeKind.COMMUNITY,
            source=NodeSource.CODE,
            name=community_name,
            path=f"community/{community_name}",
            metadata={
                "member_count": len(member_indices),
                "modularity": modularity,
                "algorithm": "leiden",
            },
        )
        community_nodes.append(community_node)
        
        # Create MEMBER_OF edges
        for idx in member_indices:
            node_id = idx_to_node_id[idx]
            node_to_community[node_id] = community_node_id
            
            edge = Edge(
                from_id=node_id,
                to_id=community_node_id,
                kind=EdgeType.MEMBER_OF,
                confidence=1.0,
                metadata={"community_name": community_name},
            )
            member_edges.append(edge)
    
    # Bulk insert into graph
    if community_nodes:
        logger.info(f"Creating {len(community_nodes)} community nodes")
        await graph.bulk_create_nodes(community_nodes)
    
    if member_edges:
        logger.info(f"Creating {len(member_edges)} MEMBER_OF edges")
        await graph.bulk_create_edges(member_edges)
    
    # Update function nodes with community_id (batched to avoid N+1)
    if node_to_community:
        updates = [
            {"node_id": nid, "community_id": cid}
            for nid, cid in node_to_community.items()
        ]
        batch_query = """
        UNWIND $updates AS u
        MATCH (n {id: u.node_id})
        SET n.community_id = u.community_id
        """
        await graph.query(batch_query, {"updates": updates})
    
    logger.info(f"Community detection complete. {len(node_to_community)} nodes clustered.")
    
    return node_to_community
