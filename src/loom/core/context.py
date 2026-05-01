from __future__ import annotations

import os
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
    1. ``~/.loom/projects/{git-root-name}.db`` — detected from git root of repo_path
    2. ``~/.loom/loom.db`` — legacy global fallback

    Args:
        repo_path: Directory to resolve from. Defaults to ``Path.cwd()``.

    Returns:
        Path to the SQLite database for this project.
    """
    # Explicit env var always wins
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
    return DEFAULT_DB_PATH


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
