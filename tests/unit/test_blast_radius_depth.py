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
    await edge_store.bulk_upsert_edges(db, [Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)])
    result = await build_blast_radius_payload(db, node_id=b.id, depth=2)
    assert result["depth"] == 2
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_blast_radius_payload_shape(db: DB) -> None:
    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)])
    result = await build_blast_radius_payload(db, node_id=b.id, depth=3)
    assert result["node_id"] == b.id
    assert result["depth"] == 3
    assert result["count"] == 1
    assert result["total"] == 1
    assert result["truncated"] is False
    assert result["next_offset"] is None
    assert result["nodes"][0]["name"] == "caller"
    assert "results" not in result  # field renamed to "nodes" in 0.4.1


@pytest.mark.asyncio
async def test_blast_radius_empty_returns_zero_count(db: DB) -> None:
    a = _fn("a.py", "lone")
    await node_store.bulk_upsert_nodes(db, [a])
    result = await build_blast_radius_payload(db, node_id=a.id, depth=3)
    assert result["count"] == 0
    assert result["nodes"] == []


@pytest.mark.asyncio
async def test_blast_radius_default_depth_is_three(db: DB) -> None:
    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)])
    result = await build_blast_radius_payload(db, node_id=b.id)
    assert result["depth"] == 3


@pytest.mark.asyncio
async def test_blast_radius_pagination(db: DB) -> None:
    """limit/offset slice the result correctly."""
    target = _fn("t.py", "target")
    callers = [_fn(f"c{i}.py", f"caller{i}") for i in range(5)]
    all_nodes = [target] + callers
    await node_store.bulk_upsert_nodes(db, all_nodes)
    edges = [Edge(from_id=c.id, to_id=target.id, kind=EdgeType.CALLS) for c in callers]
    await edge_store.bulk_upsert_edges(db, edges)

    result = await build_blast_radius_payload(db, node_id=target.id, depth=1, limit=2, offset=0)
    assert result["total"] == 5
    assert len(result["nodes"]) == 2
    assert result["truncated"] is True
    assert result["next_offset"] == 2

    result2 = await build_blast_radius_payload(db, node_id=target.id, depth=1, limit=2, offset=4)
    assert len(result2["nodes"]) == 1
    assert result2["truncated"] is False
    assert result2["next_offset"] is None
