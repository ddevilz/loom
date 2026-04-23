from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli
from loom.core.context import DB

runner = CliRunner()


def test_cli_sync_happy_path(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.incremental import SyncResult

    async def fake_sync_paths(db, path, *, old_sha=None, new_sha=None):
        return SyncResult(files_changed=2, nodes_written=8, edges_written=3)

    monkeypatch.setattr("loom.cli.ingest.sync_paths", fake_sync_paths)

    r = runner.invoke(
        loom.cli.app,
        ["sync", str(tmp_path), "--old-sha", "abc123", "--new-sha", "def456"],
        obj={"db": DB(path=":memory:")},
    )
    assert r.exit_code == 0
    assert "2" in r.stdout  # files_changed


def test_cli_sync_no_changes(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.incremental import SyncResult

    async def fake_sync_paths(db, path, *, old_sha=None, new_sha=None):
        return SyncResult(files_changed=0, nodes_written=0, edges_written=0)

    monkeypatch.setattr("loom.cli.ingest.sync_paths", fake_sync_paths)

    r = runner.invoke(
        loom.cli.app,
        ["sync", str(tmp_path)],
        obj={"db": DB(path=":memory:")},
    )
    assert r.exit_code == 0
    assert "0" in r.stdout
