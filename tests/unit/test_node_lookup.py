from __future__ import annotations

import pytest

from loom.core.context import DB
from loom.core.node import Node, NodeKind, NodeSource
from loom.query.node_lookup import resolve_node_id
from loom.store import nodes as node_store


@pytest.mark.asyncio
async def test_resolve_node_id_direct_id_passthrough() -> None:
    db = DB(path=":memory:")
    result = await resolve_node_id(db, target="function:src/a.py:foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_single_match() -> None:
    db = DB(path=":memory:")
    await node_store.bulk_upsert_nodes(db, [
        Node(
            id="function:src/a.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="src/a.py",
            language="python",
            metadata={},
        )
    ])
    result = await resolve_node_id(db, target="foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_no_match_returns_none() -> None:
    db = DB(path=":memory:")
    result = await resolve_node_id(db, target="no_such_function")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_ambiguous_returns_none() -> None:
    db = DB(path=":memory:")
    await node_store.bulk_upsert_nodes(db, [
        Node(
            id="function:src/a.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
        Node(
            id="function:src/b.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="src/b.py",
            language="python",
            metadata={},
        ),
    ])
    result = await resolve_node_id(db, target="foo", limit=2)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_kind_filter() -> None:
    db = DB(path=":memory:")
    await node_store.bulk_upsert_nodes(db, [
        Node(
            id="function:src/a.py:Foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="Foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
        Node(
            id="class:src/a.py:Foo",
            kind=NodeKind.CLASS,
            source=NodeSource.CODE,
            name="Foo",
            path="src/a.py",
            language="python",
            metadata={},
        ),
    ])
    result = await resolve_node_id(db, target="Foo", kind=NodeKind.CLASS, limit=5)
    assert result == "class:src/a.py:Foo"
