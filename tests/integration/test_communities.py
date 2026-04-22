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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_communities_creates_community_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    auth_names = ["login", "logout", "validate", "refresh"]
    data_names = ["fetch", "store", "delete", "update"]
    auth_nodes = [_func(f"auth_{n}", "src/auth.py", 10 + i * 5) for i, n in enumerate(auth_names)]
    data_nodes = [_func(f"data_{n}", "src/data.py", 20 + i * 5) for i, n in enumerate(data_names)]

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

    # Verify community_id set on function nodes
    sample = await g.get_node(auth_nodes[0].id)
    assert sample is not None
    assert sample.community_id is not None


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
