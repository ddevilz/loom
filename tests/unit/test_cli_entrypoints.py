from __future__ import annotations

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


<<<<<<< HEAD
def test_cli_help_shows_core_commands() -> None:
    r = runner.invoke(loom.cli.app, ["--help"])
=======
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
                return [
                    {"out_calls": 3, "kind": "function", "name": "main", "path": "x"}
                ]
            return [
                {
                    "kind": "function",
                    "name": "main",
                    "path": "x",
                    "id": "function:x:main",
                }
            ]

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(
        loom.cli.app, ["entrypoints", "--graph-name", "g", "--limit", "5"]
    )
>>>>>>> main
    assert r.exit_code == 0
    for cmd in ("analyze", "sync", "query", "callers", "callees", "blast-radius", "stats"):
        assert cmd in r.stdout


def test_cli_stats_runs(monkeypatch) -> None:
    class FakeGraph:
        def __init__(self, db_path=None) -> None:
            pass

        async def stats(self):
            return {"nodes": 10, "edges": 5, "nodes_by_kind": {}, "edges_by_kind": {}}

    monkeypatch.setattr("loom.cli.graph.LoomGraph", FakeGraph)

    r = runner.invoke(loom.cli.app, ["stats"])
    assert r.exit_code == 0
    assert "nodes" in r.stdout
