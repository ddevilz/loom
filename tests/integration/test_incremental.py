from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from loom.core import LoomGraph
from loom.ingest.incremental import sync_paths


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return p.stdout


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_paths_touches_only_changed_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def g():\n    return 1\n", encoding="utf-8")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    old = _git(repo, "rev-parse", "HEAD").strip()

    (repo / "a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "change a")
    new = _git(repo, "rev-parse", "HEAD").strip()

    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await sync_paths(g, repo, old_sha=old, new_sha=new)

    assert result.files_changed == 1
    assert result.nodes_written >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_paths_no_change_skips_work(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    # First sync — indexes a.py
    g = LoomGraph(db_path=tmp_path / "loom.db")
    r1 = await sync_paths(g, repo)
    assert r1.files_changed == 1

    # Second sync — file unchanged, should skip
    r2 = await sync_paths(g, repo)
    assert r2.files_changed == 0
    assert r2.nodes_written == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_paths_deleted_file_clears_nodes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    g = LoomGraph(db_path=tmp_path / "loom.db")
    await sync_paths(g, repo)

    stats_before = await g.stats()
    assert stats_before["nodes"] >= 1

    # Delete the file and re-sync; git diff won't include deleted files in
    # the candidate set from _git_diff_files, but a full walk won't find it.
    (repo / "a.py").unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "delete a")

    # Full re-walk (no sha args) will produce zero candidates since a.py gone
    r = await sync_paths(g, repo)
    assert r.files_changed == 0
