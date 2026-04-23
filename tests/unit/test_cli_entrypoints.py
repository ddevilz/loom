from __future__ import annotations

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_help_shows_core_commands() -> None:
    r = runner.invoke(loom.cli.app, ["--help"])
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
