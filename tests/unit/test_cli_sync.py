from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


<<<<<<< HEAD
def test_cli_sync_happy_path(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.incremental import SyncResult
=======
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
    warnings: list = ()  # type: ignore[assignment]
>>>>>>> main

    async def fake_sync_paths(graph, path, *, old_sha=None, new_sha=None):
        return SyncResult(files_changed=2, nodes_written=8, edges_written=3)

    class _FakeGraphSyncHappy:
        def __init__(self, db_path=None) -> None:
            pass

<<<<<<< HEAD
    monkeypatch.setattr("loom.cli.ingest.LoomGraph", _FakeGraphSyncHappy)
    monkeypatch.setattr("loom.ingest.incremental.sync_paths", fake_sync_paths)
=======
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
>>>>>>> main

    r = runner.invoke(
        loom.cli.app,
        ["sync", str(tmp_path), "--old-sha", "abc123", "--new-sha", "def456"],
    )
    assert r.exit_code == 0
    assert "2" in r.stdout  # files_changed


def test_cli_sync_no_changes(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.incremental import SyncResult

    async def fake_sync_paths(graph, path, *, old_sha=None, new_sha=None):
        return SyncResult(files_changed=0, nodes_written=0, edges_written=0)

    class _FakeGraphSyncEmpty:
        def __init__(self, db_path=None) -> None:
            pass

    monkeypatch.setattr("loom.cli.ingest.LoomGraph", _FakeGraphSyncEmpty)
    monkeypatch.setattr("loom.ingest.incremental.sync_paths", fake_sync_paths)

    r = runner.invoke(loom.cli.app, ["sync", str(tmp_path)])
    assert r.exit_code == 0
    assert "0" in r.stdout
