from __future__ import annotations

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_query_prints_search_results(monkeypatch) -> None:
    from loom.core import Node, NodeKind, NodeSource
    from loom.query.search import SearchResult

    node = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        metadata={},
    )

<<<<<<< HEAD
    async def fake_search(query, graph, *, limit=10):
        return [SearchResult(node=node, score=1.0)]

    monkeypatch.setattr("loom.cli.graph.search_nodes", fake_search)
=======
            self.node = Node(
                id="function:x:f",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name="f",
                path="x",
                metadata={},
            )
            self.score = 0.9
            self.matched_via = "vector"

    async def fake_search(
        query_text, graph, *, limit=10, expand_depth=1, embedder=None
    ):
        return [Result()]

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.search.searcher.search", fake_search)
>>>>>>> main

    result = runner.invoke(loom.cli.app, ["query", "how does auth work?"])
    assert result.exit_code == 0
    assert "f" in result.stdout
