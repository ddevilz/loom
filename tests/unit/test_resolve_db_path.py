from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from loom.core.context import _PROJECTS_DIR, resolve_db_path


def test_non_git_fallback_uses_cwd_name(tmp_path: Path) -> None:
    """Non-git dir → ~/.loom/projects/{dirname}.db (not loom.db)."""
    with patch("loom.core.context.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1  # simulate: not a git repo

        with patch("loom.core.context.Path.cwd", return_value=tmp_path):
            result = resolve_db_path()

    assert result == _PROJECTS_DIR / f"{tmp_path.name}.db"
    assert result != Path.home() / ".loom" / "loom.db"


def test_non_git_migration_copies_legacy_db(tmp_path: Path) -> None:
    """If new per-project DB empty and legacy ~/.loom/loom.db exists → copy it."""
    legacy = tmp_path / "loom.db"
    legacy.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)  # minimal SQLite header

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    expected_db = projects_dir / "myproject.db"

    with patch("loom.core.context.subprocess.run") as mock_run, \
         patch("loom.core.context._PROJECTS_DIR", projects_dir), \
         patch("loom.core.context.DEFAULT_DB_PATH", legacy), \
         patch("loom.core.context.Path.cwd", return_value=project_dir):
        mock_run.return_value.returncode = 1

        result = resolve_db_path()

    assert result == expected_db
    assert expected_db.exists()


def test_non_git_no_migration_if_marker_exists(tmp_path: Path) -> None:
    """Skip migration if .migrated marker exists beside legacy DB."""
    legacy = tmp_path / "loom.db"
    legacy.write_bytes(b"SQLite format 3\x00" + b"\x00" * 84)
    marker = tmp_path / "loom.migrated"
    marker.touch()

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    expected_db = projects_dir / "myproject.db"

    with patch("loom.core.context.subprocess.run") as mock_run, \
         patch("loom.core.context._PROJECTS_DIR", projects_dir), \
         patch("loom.core.context.DEFAULT_DB_PATH", legacy), \
         patch("loom.core.context.Path.cwd", return_value=project_dir):
        mock_run.return_value.returncode = 1

        result = resolve_db_path()

    assert result == expected_db
    assert not expected_db.exists()  # migration skipped


def test_env_override_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOM_DB_PATH", str(tmp_path / "explicit.db"))
    result = resolve_db_path()
    assert result == tmp_path / "explicit.db"
