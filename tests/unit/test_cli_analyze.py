from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

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
        jira=None,
    ):
        calls["path"] = path
        calls["force"] = force
        calls["exclude_tests"] = exclude_tests
        calls["docs_path"] = docs_path
        calls["jira"] = jira
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
            "--jira-project",
            "PROJ",
            "--jira-url",
            "https://jira.example.com",
            "--jira-email",
            "a@b.com",
            "--jira-token",
            "tok",
            "--graph-name",
            "test_graph",
            "--exclude-tests",
            "--force",
        ],
    )

    assert result.exit_code == 0

    assert calls["graph_name"] == "test_graph"
    assert (
        Path(str(calls["path"])).resolve()
        == Path("tests/fixtures/sample_repo").resolve()
    )
    assert calls["exclude_tests"] is True
    assert calls["force"] is True
    assert calls["jira"].project_key == "PROJ"

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


def test_cli_analyze_prints_error_details(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            pass

        async def query(self, cypher: str, params=None):
            if cypher.startswith("MATCH (n) RETURN n.kind AS kind"):
                return [{"kind": "file", "c": 1}]
            return []

    async def fake_index_repo(
        path: str,
        graph,
        *,
        force: bool = False,
        exclude_tests: bool = False,
        docs_path: str | None = None,
        jira=None,
    ):
        return SimpleNamespace(
            node_count=1,
            edge_count=0,
            file_count=1,
            files_skipped=0,
            files_updated=0,
            files_added=1,
            files_deleted=0,
            error_count=1,
            duration_ms=10.0,
            errors=[
                SimpleNamespace(
                    phase="embed",
                    path="repo",
                    message="model.onnx missing",
                )
            ],
        )

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.ingest.pipeline.index_repo", fake_index_repo)

    result = runner.invoke(loom.cli.app, ["analyze", "tests/fixtures/sample_repo"])

    assert result.exit_code == 0
    assert "Errors" in result.stdout
    assert "embed" in result.stdout
    assert "model.onnx missing" in result.stdout


def test_cli_enrich_infers_repo_path_for_coupling(monkeypatch):
    calls: dict[str, object] = {}

    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            calls["graph_name"] = graph_name

        async def query(self, cypher: str, params=None):
            if (
                cypher
                == "MATCH (n) WHERE n.kind = 'file' RETURN n.path AS path LIMIT 1000"
            ):
                return [
                    {"path": "/repo/src/a.py"},
                    {"path": "/repo/src/b.py"},
                    {"path": "/repo/README.md"},
                ]
            return []

        async def bulk_create_edges(self, edges):
            calls["edges"] = edges

    async def fake_detect_communities(graph):
        calls["communities_graph"] = graph
        return {}

    async def fake_analyze_coupling(
        repo_path: str, *, months: int = 6, threshold: float = 0.3
    ):
        calls["repo_path"] = repo_path
        calls["months"] = months
        calls["threshold"] = threshold
        return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr(
        "loom.analysis.code.communities.detect_communities", fake_detect_communities
    )
    monkeypatch.setattr(
        "loom.analysis.code.coupling.analyze_coupling", fake_analyze_coupling
    )

    result = runner.invoke(
        loom.cli.app,
        ["enrich", "--graph-name", "test_graph", "--coupling-months", "3"],
    )

    assert result.exit_code == 0
    assert calls["graph_name"] == "test_graph"
    assert Path(str(calls["repo_path"])) == Path("/repo")
    assert calls["months"] == 3
    assert calls["threshold"] == 0.3


def test_cli_enrich_uses_explicit_repo_path_override(monkeypatch):
    calls: dict[str, object] = {}

    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            pass

        async def query(self, cypher: str, params=None):
            raise AssertionError(
                "repo root inference should not run when --repo-path is provided"
            )

        async def bulk_create_edges(self, edges):
            calls["edges"] = edges

    async def fake_detect_communities(graph):
        return {}

    async def fake_analyze_coupling(
        repo_path: str, *, months: int = 6, threshold: float = 0.3
    ):
        calls["repo_path"] = repo_path
        return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr(
        "loom.analysis.code.communities.detect_communities", fake_detect_communities
    )
    monkeypatch.setattr(
        "loom.analysis.code.coupling.analyze_coupling", fake_analyze_coupling
    )

    result = runner.invoke(
        loom.cli.app,
        ["enrich", "--repo-path", r"F:\explicit-repo", "--no-communities"],
    )

    assert result.exit_code == 0
    assert Path(str(calls["repo_path"])) == Path(r"F:\explicit-repo")
