from __future__ import annotations

import asyncio
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


async def _first_community_id(db: DB) -> str:
    def _run() -> str:
        with db._lock:
            conn = db.connect()
            row = conn.execute(
                "SELECT id FROM nodes WHERE kind = 'community' LIMIT 1"
            ).fetchone()
            return row["id"] if row else ""
    return await asyncio.to_thread(_run)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_communities_creates_community_nodes(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    auth_names = ["login", "logout", "validate", "refresh"]
    data_names = ["fetch", "store", "delete", "update"]
    auth_nodes = [_func(f"auth_{n}", "src/auth.py", 10 + i * 5) for i, n in enumerate(auth_names)]
    data_nodes = [_func(f"data_{n}", "src/data.py", 20 + i * 5) for i, n in enumerate(data_names)]

    await node_store.bulk_upsert_nodes(db, auth_nodes + data_nodes)

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
    cross_edge = Edge(from_id=auth_nodes[0].id, to_id=data_nodes[0].id, kind=EdgeType.CALLS)

    await edge_store.bulk_upsert_edges(db, auth_edges + data_edges + [cross_edge])

    count = await compute_communities(db)
    assert count >= 1, "Should detect at least 1 community"

    members = await traversal.community_members(db, await _first_community_id(db))
    assert len(members) >= 2

    sample = await node_store.get_node(db, auth_nodes[0].id)
    assert sample is not None
    assert sample.community_id is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_communities_handles_empty_graph(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")
    count = await compute_communities(db)
    assert count == 0
