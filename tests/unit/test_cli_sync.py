from __future__ import annotations

from dataclasses import dataclass

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


@dataclass(frozen=True)
class _FakeIndexResult:
    node_count: int = 10
    edge_count: int = 5
    file_count: int = 3
    files_skipped: int = 0
    files_updated: int = 1
    files_added: int = 1
    files_deleted: int = 1
    error_count: int = 0
    duration_ms: float = 10.0
    errors: list = None  # type: ignore[assignment]


def test_cli_sync_happy_path(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

    async def fake_get_changed_files(repo_path: str, old_sha: str, new_sha: str):
        class FC:
            def __init__(
                self, status: str, path: str, old_path: str | None = None
            ) -> None:
                self.status = status
                self.path = path
                self.old_path = old_path

        return [FC("M", "a.py"), FC("A", "b.ts"), FC("D", "c.java")]

    async def fake_sync_commits(repo_path: str, old_sha: str, new_sha: str, graph):
        return _FakeIndexResult()

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.ingest.git.get_changed_files", fake_get_changed_files)
    monkeypatch.setattr("loom.ingest.incremental.sync_commits", fake_sync_commits)

    r = runner.invoke(
        loom.cli.app,
        [
            "sync",
            "--old-sha",
            "abc",
            "--new-sha",
            "def",
            "--graph-name",
            "g",
            "--repo-path",
            ".",
        ],
    )
    assert r.exit_code == 0
    assert "Syncing abc..def" in r.stdout
    assert "files_updated" in r.stdout


def test_cli_sync_invalid_refs_exits_1(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

    async def fake_get_changed_files(repo_path: str, old_sha: str, new_sha: str):
        raise RuntimeError("bad refs")

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.ingest.git.get_changed_files", fake_get_changed_files)

    r = runner.invoke(
        loom.cli.app,
        [
            "sync",
            "--old-sha",
            "abc",
            "--new-sha",
            "def",
            "--graph-name",
            "g",
            "--repo-path",
            ".",
        ],
    )
    assert r.exit_code == 1
