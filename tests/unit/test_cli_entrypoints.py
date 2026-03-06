from __future__ import annotations

from typer.testing import CliRunner

import loom.cli


runner = CliRunner()


def test_cli_entrypoints_runs_queries(monkeypatch):
    seen: list[str] = []

    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

        async def query(self, cypher: str, params=None):
            seen.append(cypher)
            if "RETURN type(r)" in cypher:
                return [{"t": "calls", "c": 1}]
            if "out_calls" in cypher:
                return [{"out_calls": 3, "kind": "function", "name": "main", "path": "x"}]
            return [{"kind": "function", "name": "main", "path": "x", "id": "function:x:main"}]

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(loom.cli.app, ["entrypoints", "--graph-name", "g", "--limit", "5"])
    assert r.exit_code == 0
    assert "name-based candidates" in r.stdout
    assert "relationship types" in r.stdout
    assert any("MATCH (n)" in q for q in seen)
