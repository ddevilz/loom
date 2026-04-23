from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from loom.core import LoomGraph
from loom.ingest.incremental import SyncResult, _validate_ref, sync_paths


def test_validate_ref_accepts_safe_chars() -> None:
    _validate_ref("abc123def")
    _validate_ref("HEAD~1")
    _validate_ref("HEAD")


def test_validate_ref_rejects_shell_metacharacters() -> None:
    import pytest
    with pytest.raises(ValueError, match="unsafe git ref"):
        _validate_ref("abc; rm -rf /")
    with pytest.raises(ValueError, match="unsafe git ref"):
        _validate_ref("abc$(whoami)")
    with pytest.raises(ValueError, match="unsafe git ref"):
        _validate_ref("")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=str(cwd), text=True, stderr=subprocess.PIPE
    )


def _init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")


@pytest.mark.asyncio
async def test_sync_paths_with_git_shas(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    old = _git(repo, "rev-parse", "HEAD").strip()

    (repo / "a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "modify a")
    new = _git(repo, "rev-parse", "HEAD").strip()

    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await sync_paths(g, repo, old_sha=old, new_sha=new)

    assert isinstance(result, SyncResult)
    assert result.files_changed == 1
    assert result.nodes_written >= 1


@pytest.mark.asyncio
async def test_sync_paths_skips_unchanged_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")

    g = LoomGraph(db_path=tmp_path / "loom.db")

    # First full scan
    r1 = await sync_paths(g, repo)
    assert r1.files_changed == 1

    # Second scan — no changes — should be a no-op
    r2 = await sync_paths(g, repo)
    assert r2.files_changed == 0
    assert r2.nodes_written == 0


@pytest.mark.asyncio
async def test_sync_paths_empty_repo_returns_zero(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    result = await sync_paths(g, tmp_path)
    assert result.files_changed == 0
    assert result.nodes_written == 0
    assert result.edges_written == 0
