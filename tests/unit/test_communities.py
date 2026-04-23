from __future__ import annotations

from pathlib import Path

import pytest

from loom.analysis.communities import compute_communities
from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.query import traversal
from loom.store import edges as edge_store
from loom.store import nodes as node_store


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
    db = DB(path=tmp_path / "loom.db")
    count = await compute_communities(db)
    assert count == 0


@pytest.mark.asyncio
async def test_compute_communities_sets_community_id_on_members(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(4)]
    await node_store.bulk_upsert_nodes(db, nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[2].id, to_id=nodes[3].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[3].id, to_id=nodes[0].id, kind=EdgeType.CALLS),
    ]
    await edge_store.bulk_upsert_edges(db, edges)

    count = await compute_communities(db)
    assert count >= 1

    for node in nodes:
        n = await node_store.get_node(db, node.id)
        assert n is not None
        assert n.community_id is not None


@pytest.mark.asyncio
async def test_compute_communities_creates_community_kind_nodes(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    names = ["login", "logout", "validate"]
    nodes = [_func(f"auth_{n}", "src/a.py", i * 5) for i, n in enumerate(names)]
    await node_store.bulk_upsert_nodes(db, nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await edge_store.bulk_upsert_edges(db, edges)

    await compute_communities(db)

    s = await traversal.stats(db)
    assert s["nodes_by_kind"].get("community", 0) >= 1


@pytest.mark.asyncio
async def test_compute_communities_idempotent(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(3)]
    await node_store.bulk_upsert_nodes(db, nodes)
    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await edge_store.bulk_upsert_edges(db, edges)

    count1 = await compute_communities(db)
    count2 = await compute_communities(db)

    assert count1 == count2

    s = await traversal.stats(db)
    community_count = s["nodes_by_kind"].get("community", 0)
    assert community_count == count2
