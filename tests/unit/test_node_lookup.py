from __future__ import annotations

import pytest

from loom.core import LoomGraph, Node, NodeKind, NodeSource
from loom.query.node_lookup import (
    resolve_node_id,
)


@pytest.mark.asyncio
async def test_resolve_node_id_direct_id_passthrough(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await resolve_node_id(g, target="function:src/a.py:foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_single_match(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
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
    result = await resolve_node_id(g, target="foo")
    assert result == "function:src/a.py:foo"


@pytest.mark.asyncio
async def test_resolve_node_id_no_match_returns_none(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await resolve_node_id(g, target="no_such_function")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_ambiguous_returns_none(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
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
    # Two matches with default limit=2 → ambiguous → returns None
    result = await resolve_node_id(g, target="foo", limit=2)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_node_id_kind_filter(tmp_path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
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
    # Filter to CLASS kind → single match
    result = await resolve_node_id(g, target="Foo", kind=NodeKind.CLASS, limit=5)
    assert result == "class:src/a.py:Foo"
