from __future__ import annotations

import pytest
from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.store import nodes as node_store


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash-" + path,
    )


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


@pytest.mark.asyncio
async def test_get_node_returns_none_when_missing(db: DB) -> None:
    result = await node_store.get_node(db, "no-such-id")
    assert result is None


@pytest.mark.asyncio
async def test_bulk_upsert_and_get(db: DB) -> None:
    a = _fn("a.py", "foo")
    await node_store.bulk_upsert_nodes(db, [a])
    got = await node_store.get_node(db, a.id)
    assert got is not None
    assert got.name == "foo"


@pytest.mark.asyncio
async def test_get_nodes_by_name(db: DB) -> None:
    a = _fn("a.py", "parse")
    b = _fn("b.py", "parse")
    await node_store.bulk_upsert_nodes(db, [a, b])
    results = await node_store.get_nodes_by_name(db, "parse")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_update_summary(db: DB) -> None:
    a = _fn("a.py", "foo")
    await node_store.bulk_upsert_nodes(db, [a])
    ok = await node_store.update_summary(db, a.id, "Does foo things")
    assert ok is True
    got = await node_store.get_node(db, a.id)
    assert got is not None and got.summary == "Does foo things"


@pytest.mark.asyncio
async def test_update_summary_missing_node(db: DB) -> None:
    ok = await node_store.update_summary(db, "no-such-id", "summary")
    assert ok is False


@pytest.mark.asyncio
async def test_get_content_hashes(db: DB) -> None:
    file_node = Node(
        id="file:a.py",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name="a.py",
        path="a.py",
        file_hash="hash-a.py",
    )
    await node_store.bulk_upsert_nodes(db, [file_node])
    hashes = await node_store.get_content_hashes(db)
    assert "a.py" in hashes
    assert hashes["a.py"][0] == "hash-a.py"


@pytest.mark.asyncio
async def test_replace_file_atomic(db: DB) -> None:
    old = _fn("a.py", "old_fn")
    await node_store.bulk_upsert_nodes(db, [old])
    new = _fn("a.py", "new_fn")
    await node_store.replace_file(db, "a.py", [new], [])
    assert await node_store.get_node(db, old.id) is None
    assert await node_store.get_node(db, new.id) is not None
