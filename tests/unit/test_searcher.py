from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import LoomGraph, Node, NodeKind, NodeSource
from loom.query.search import SearchResult, search


@pytest.mark.asyncio
async def test_search_returns_matching_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
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

    results = await search("authenticate", g, limit=5)
    assert isinstance(results, list)
    ids = [r.node.id for r in results]
    assert "function:src/a.py:authenticate" in ids


@pytest.mark.asyncio
async def test_search_returns_search_result_with_score(tmp_path: Path) -> None:
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
    ])

    results = await search("foo", g, limit=5)
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.node.name == "foo"
    assert r.score == 1.0


@pytest.mark.asyncio
async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    results = await search("xyzzy_no_match", g, limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_respects_limit(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    await g.bulk_upsert_nodes([
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

    results = await search("func", g, limit=3)
    assert len(results) <= 3
