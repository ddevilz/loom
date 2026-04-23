from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loom.core.context import DB
from loom.query.search import search
from loom.store import edges as edge_store
from loom.store import nodes as node_store

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fixtures.sample_graph import build_searchable_sample_graph


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_by_name_returns_matches(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await node_store.bulk_upsert_nodes(db, fixture["nodes"])
    await edge_store.bulk_upsert_edges(db, fixture["edges"])

    results = await search("validate_user", db, limit=5)
    ids = [r.node.id for r in results]
    assert any(node_id.endswith(":validate_user") for node_id in ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_partial_name_returns_matches(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await node_store.bulk_upsert_nodes(db, fixture["nodes"])

    results = await search("parse", db, limit=10)
    names = {r.node.name for r in results}
    assert "parse_token" in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await node_store.bulk_upsert_nodes(db, fixture["nodes"])

    results = await search("xyzzy_nonexistent_9999", db, limit=5)
    assert results == []
