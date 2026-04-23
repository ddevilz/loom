from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loom.core import LoomGraph

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fixtures.sample_graph import build_searchable_sample_graph


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_by_name_returns_matches(tmp_path: Path) -> None:
    graph = LoomGraph(db_path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await graph.bulk_upsert_nodes(fixture["nodes"])
    await graph.bulk_upsert_edges(fixture["edges"])

    results = await graph.search("validate_user", limit=5)
    ids = [r.id for r in results]
    assert any(node_id.endswith(":validate_user") for node_id in ids)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_partial_name_returns_matches(tmp_path: Path) -> None:
    graph = LoomGraph(db_path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await graph.bulk_upsert_nodes(fixture["nodes"])

    results = await graph.search("parse", limit=10)
    names = {r.name for r in results}
    assert "parse_token" in names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_no_match_returns_empty(tmp_path: Path) -> None:
    graph = LoomGraph(db_path=tmp_path / "loom.db")

    fixture = build_searchable_sample_graph()
    await graph.bulk_upsert_nodes(fixture["nodes"])

    results = await graph.search("xyzzy_nonexistent_9999", limit=5)
    assert results == []
