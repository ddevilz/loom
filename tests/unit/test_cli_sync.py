from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_sync_happy_path(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.incremental import SyncResult

    async def fake_sync_paths(graph, path, *, old_sha=None, new_sha=None):
        return SyncResult(files_changed=2, nodes_written=8, edges_written=3)

    class _FakeGraphSyncHappy:
        def __init__(self, db_path=None) -> None:
            pass

    monkeypatch.setattr("loom.cli.ingest.LoomGraph", _FakeGraphSyncHappy)
    monkeypatch.setattr("loom.ingest.incremental.sync_paths", fake_sync_paths)

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
