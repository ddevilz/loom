from __future__ import annotations

from typer.testing import CliRunner

import loom.cli
from loom.core.context import DB

runner = CliRunner()


def test_cli_help_shows_core_commands() -> None:
    r = runner.invoke(loom.cli.app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("analyze", "sync", "query", "callers", "callees", "blast-radius", "stats"):
        assert cmd in r.stdout


def test_cli_stats_runs(monkeypatch) -> None:
    async def fake_stats(db):
        return {"nodes": 10, "edges": 5, "nodes_by_kind": {}, "edges_by_kind": {}}

    monkeypatch.setattr("loom.cli.graph.traversal.stats", fake_stats)

    r = runner.invoke(
        loom.cli.app,
        ["stats"],
        obj={"db": DB(path=":memory:")},
    )
    assert r.exit_code == 0
    assert "nodes" in r.stdout
