from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_help_shows_analyze_command() -> None:
    result = runner.invoke(loom.cli.app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_cli_analyze_calls_index_repo(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    fake_result = IndexResult(
        repo_path=tmp_path,
        files_parsed=5,
        files_skipped=1,
        nodes_written=20,
        edges_written=10,
    )

    async def fake_index_repo(path, graph, **kw):
        return fake_result

    monkeypatch.setattr("loom.ingest.pipeline.index_repo", fake_index_repo)

    result = runner.invoke(
        loom.cli.app,
        ["analyze", str(tmp_path)],
    )

    assert result.exit_code == 0
<<<<<<< HEAD
    assert "5" in result.stdout  # files_parsed
=======

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
>>>>>>> main


def test_cli_analyze_uses_db_flag(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    db_path_list: list[Path] = []

    class FakeGraph:
        def __init__(self, db_path: Path | None = None) -> None:
            if db_path:
                db_path_list.append(db_path)

    async def fake_index_repo(path, graph, **kw):
        return IndexResult(
            repo_path=tmp_path,
            files_parsed=0,
            files_skipped=0,
            nodes_written=0,
            edges_written=0,
        )

    monkeypatch.setattr("loom.cli.ingest.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.ingest.pipeline.index_repo", fake_index_repo)

    custom_db = tmp_path / "custom.db"
    result = runner.invoke(
        loom.cli.app,
        ["analyze", str(tmp_path), "--db", str(custom_db)],
    )

    assert result.exit_code == 0
<<<<<<< HEAD
    assert len(db_path_list) == 1
    assert db_path_list[0] == custom_db


def test_cli_analyze_shows_errors(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    async def fake_index_repo(path, graph, **kw):
        return IndexResult(
            repo_path=tmp_path,
            files_parsed=1,
            files_skipped=0,
            nodes_written=1,
            edges_written=0,
            errors=["parse failed src/a.py: SyntaxError"],
        )

    monkeypatch.setattr("loom.ingest.pipeline.index_repo", fake_index_repo)

    result = runner.invoke(loom.cli.app, ["analyze", str(tmp_path)])

    assert result.exit_code == 0
    assert "warn" in result.stdout or "parse failed" in result.stdout
=======
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
                == "MATCH (n:File) RETURN n.path AS path LIMIT 1000"
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
>>>>>>> main
