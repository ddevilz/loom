from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typer.testing import CliRunner

import loom.cli


runner = CliRunner()


@dataclass(frozen=True)
class _FakeIndexResult:
    node_count: int = 123
    edge_count: int = 456
    file_count: int = 10
    files_skipped: int = 1
    files_updated: int = 2
    files_added: int = 3
    files_deleted: int = 4

    error_count: int = 0
    duration_ms: float = 12.0


def test_cli_analyze_wires_flags_and_prints_summary(monkeypatch):
    calls: dict[str, object] = {}

    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            calls["graph_name"] = graph_name

        async def query(self, cypher: str, params=None):
            if cypher == "MATCH (n) RETURN count(n) AS c":
                return [{"c": 123}]
            if cypher == "MATCH ()-[r]->() RETURN count(r) AS c":
                return [{"c": 456}]
            if cypher.startswith("MATCH (n) RETURN n.kind AS kind"):
                return [{"kind": "file", "c": 80}]
            return []

    async def fake_index_repo(
        path: str,
        graph,
        *,
        force: bool = False,
        exclude_tests: bool = False,
        docs_path: str | None = None,
    ):
        calls["path"] = path
        calls["force"] = force
        calls["exclude_tests"] = exclude_tests
        calls["docs_path"] = docs_path
        calls["graph"] = graph
        return _FakeIndexResult()

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.ingest.pipeline.index_repo", fake_index_repo)

    result = runner.invoke(
        loom.cli.app,
        [
            "analyze",
            "tests/fixtures/sample_repo",
            "--docs",
            "docs",
            "--graph-name",
            "test_graph",
            "--exclude-tests",
            "--force",
        ],
    )

    assert result.exit_code == 0

    assert calls["graph_name"] == "test_graph"
    assert Path(str(calls["path"])) == Path("tests/fixtures/sample_repo")
    assert calls["exclude_tests"] is True
    assert calls["force"] is True

    # Rich output should include our result fields
    out = result.stdout
    assert "files_skipped" in out
    assert "files_updated" in out
    assert "files_added" in out
    assert "files_deleted" in out
    assert "nodes" in out
    assert "edges" in out


def test_cli_help_shows_analyze_command():
    result = runner.invoke(loom.cli.app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout
