"""Tests for blast_radius payload builder."""

from __future__ import annotations

import pytest

from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.query.blast_radius import build_blast_radius_payload
from loom.store import edges as edge_store
from loom.store import nodes as node_store


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash",
    )


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


@pytest.mark.asyncio
async def test_blast_radius_forwards_depth_to_graph(db: DB) -> None:
    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    result = await build_blast_radius_payload(db, node_id=b.id, depth=2)
    assert result["depth"] == 2
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_blast_radius_payload_shape(db: DB) -> None:
    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    result = await build_blast_radius_payload(db, node_id=b.id, depth=3)
    assert result["node_id"] == b.id
    assert result["depth"] == 3
    assert result["count"] == 1
    assert result["results"][0]["name"] == "caller"


@pytest.mark.asyncio
async def test_blast_radius_empty_returns_zero_count(db: DB) -> None:
    a = _fn("a.py", "lone")
    await node_store.bulk_upsert_nodes(db, [a])
    result = await build_blast_radius_payload(db, node_id=a.id, depth=3)
    assert result["count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_blast_radius_default_depth_is_three(db: DB) -> None:
    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [
        Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)
    ])
    result = await build_blast_radius_payload(db, node_id=b.id)
    assert result["depth"] == 3
