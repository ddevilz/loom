from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from loom.core.db import connect, has_fts5, init_schema

DEFAULT_DB_PATH: Path = Path.home() / ".loom" / "loom.db"
_PROJECTS_DIR: Path = Path.home() / ".loom" / "projects"


def resolve_db_path(repo_path: Path | None = None) -> Path:
    """Auto-resolve DB path for the current project.

    Resolution order:
    1. LOOM_DB_PATH env var — explicit override
    2. ~/.loom/projects/{git-root-name}.db — from git root
    3. ~/.loom/projects/{cwd-name}.db — non-git fallback (auto-detect)

    For tier 3: if new DB does not exist and legacy ~/.loom/loom.db exists,
    copies it once (silent migration). Skips copy if .migrated marker present.
    """
    env_override = os.getenv("LOOM_DB_PATH")
    if env_override:
        return Path(env_override)

    base = (repo_path or Path.cwd()).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=3,
        )
        if result.returncode == 0:
            git_root = Path(result.stdout.strip())
            project_name = git_root.name
            _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
            return _PROJECTS_DIR / f"{project_name}.db"
    except Exception:
        pass

    # Non-git fallback: use cwd folder name
    project_name = Path.cwd().name
    _PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    new_path = _PROJECTS_DIR / f"{project_name}.db"

    # One-time silent migration from legacy flat DB
    if not new_path.exists():
        marker = DEFAULT_DB_PATH.with_suffix(".migrated")
        if DEFAULT_DB_PATH.exists() and not marker.exists():
            try:
                shutil.copy2(DEFAULT_DB_PATH, new_path)
                marker.touch()
            except Exception:
                pass  # migration failure is non-fatal

    return new_path


@dataclass
class DB:
    path: Path | str
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _fts5: bool | None = field(default=None, init=False, repr=False)

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = connect(self.path)
                init_schema(self._conn)
                self._fts5 = has_fts5(self._conn)
            return self._conn
