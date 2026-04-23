from __future__ import annotations

from pathlib import Path

import pytest

from loom.analysis.communities import compute_communities
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource


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


@pytest.mark.asyncio
async def test_compute_communities_empty_graph_returns_zero(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    count = await compute_communities(g)
    assert count == 0


@pytest.mark.asyncio
async def test_compute_communities_sets_community_id_on_members(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(4)]
    await g.bulk_upsert_nodes(nodes)

    # Dense ring of CALLS edges
    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[2].id, to_id=nodes[3].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[3].id, to_id=nodes[0].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_upsert_edges(edges)

    count = await compute_communities(g)
    assert count >= 1

    # community_id should be set on all function nodes
    for node in nodes:
        n = await g.get_node(node.id)
        assert n is not None
        assert n.community_id is not None


@pytest.mark.asyncio
async def test_compute_communities_creates_community_kind_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    names = ["login", "logout", "validate"]
    nodes = [_func(f"auth_{n}", "src/a.py", i * 5) for i, n in enumerate(names)]
    await g.bulk_upsert_nodes(nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_upsert_edges(edges)

    await compute_communities(g)

    stats = await g.stats()
    assert stats["nodes_by_kind"].get("community", 0) >= 1


@pytest.mark.asyncio
async def test_compute_communities_idempotent(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(3)]
    await g.bulk_upsert_nodes(nodes)
    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_upsert_edges(edges)

    count1 = await compute_communities(g)
    count2 = await compute_communities(g)

    # Second run should produce same number of communities (old ones cleared first)
    assert count1 == count2

    stats = await g.stats()
    # Should not accumulate duplicate community nodes
    community_count = stats["nodes_by_kind"].get("community", 0)
    assert community_count == count2
