from __future__ import annotations

import pytest

from loom.core.context import DB
from loom.core.node import Node, NodeKind, NodeSource
from loom.query.search import SearchResult, search
from loom.store import nodes as node_store


@pytest.mark.asyncio
async def test_search_returns_matching_nodes() -> None:
    db = DB(path=":memory:")
    await node_store.bulk_upsert_nodes(db, [
        Node(
            id="function:src/a.py:authenticate",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="authenticate",
            path="src/a.py",
            language="python",
            metadata={},
        ),
        Node(
            id="function:src/a.py:authorize",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="authorize",
            path="src/a.py",
            language="python",
            metadata={},
        ),
    ])
    results = await search("authenticate", db, limit=5)
    assert isinstance(results, list)
    ids = [r.node.id for r in results]
    assert "function:src/a.py:authenticate" in ids


@pytest.mark.asyncio
async def test_search_returns_search_result_with_score() -> None:
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
    ])
    results = await search("foo", db, limit=5)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.node.name == "foo"
    assert r.score >= 0  # real BM25 score — positive, magnitude varies with corpus size


@pytest.mark.asyncio
async def test_search_no_match_returns_empty() -> None:
    db = DB(path=":memory:")
    results = await search("xyzzy_no_match", db, limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_respects_limit() -> None:
    db = DB(path=":memory:")
    await node_store.bulk_upsert_nodes(db, [
        Node(
            id=f"function:src/a.py:func_{i}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=f"func_{i}",
            path="src/a.py",
            language="python",
            metadata={},
        )
        for i in range(20)
    ])
    results = await search("func", db, limit=3)
    assert len(results) <= 3
