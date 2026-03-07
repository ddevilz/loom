from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import loom.cli
from loom.core import LoomGraph
from loom.core.falkor import cypher
from loom.search.searcher import search

sys.path.append(str(Path(__file__).resolve().parents[1]))
from fixtures.sample_graph import build_searchable_sample_graph


runner = CliRunner()


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_e2e_returns_ranked_code_and_doc_results() -> None:
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    graph = LoomGraph(graph_name="loom_pytest_search_e2e")
    await graph.query(cypher.CLEAR_GRAPH)

    fixture = build_searchable_sample_graph()
    await graph.bulk_create_nodes(fixture["nodes"])
    await graph.bulk_create_edges(fixture["edges"])

    results = await search("authentication password policy", graph, limit=5, embedder=_FakeEmbedder())
    ids = [result.node.id for result in results]

    assert any(node_id.endswith(":validate_user") for node_id in ids)
    assert "doc:spec.pdf:1.0" in ids


@pytest.mark.integration
def test_query_cli_e2e_prints_real_graph_results(monkeypatch) -> None:
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    graph = LoomGraph(graph_name="loom_pytest_query_cli_e2e")

    import asyncio

    async def _seed() -> None:
        await graph.query(cypher.CLEAR_GRAPH)
        fixture = build_searchable_sample_graph()
        await graph.bulk_create_nodes(fixture["nodes"])
        await graph.bulk_create_edges(fixture["edges"])

    asyncio.run(_seed())

    monkeypatch.setattr("loom.search.searcher.FastEmbedder", _FakeEmbedder)

    result = runner.invoke(
        loom.cli.app,
        ["query", "authentication password policy", "--graph-name", "loom_pytest_query_cli_e2e", "--limit", "5"],
    )

    assert result.exit_code == 0
    assert "validate_user" in result.stdout
    assert "spec.pdf" in result.stdout
