from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

_FTS5_PROBE = "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x);"
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DB_PATH: Path = Path.home() / ".loom" / "loom.db"
_PROJECTS_DIR: Path = Path.home() / ".loom" / "projects"


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def has_fts5(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SAVEPOINT _fts5_check")
        conn.execute(_FTS5_PROBE)
        conn.execute("DROP TABLE _fts5_probe")
        conn.execute("RELEASE SAVEPOINT _fts5_check")
        return True
    except sqlite3.OperationalError:
        conn.execute("ROLLBACK TO SAVEPOINT _fts5_check")
        conn.execute("RELEASE SAVEPOINT _fts5_check")
        return False


def _load_schema() -> tuple[str, str]:
    """Read schema.sql and split into CORE and FTS5 sections.

    Returns:
        (core_ddl, fts5_ddl) — strings suitable for executescript().
    """
    text = _SCHEMA_PATH.read_text(encoding="utf-8")
    if "-- @fts5" in text:
        core, fts5 = text.split("-- @fts5", 1)
    else:
        core, fts5 = text, ""
    return core, fts5


_DDL_CORE, _DDL_FTS5 = _load_schema()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, typedef: str) -> None:
    """Add a column to an existing table if it doesn't already exist.

    SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS.
    Uses PRAGMA table_info as workaround.

    Args:
        conn: SQLite connection.
        table: Table name.
        col: Column name to add.
        typedef: Column type + constraints (e.g. 'TEXT', 'INTEGER DEFAULT 0').
    """
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
        conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL_CORE)
    if has_fts5(conn):
        conn.executescript(_DDL_FTS5)
    conn.commit()
    # Migrations for existing databases (idempotent)
    _add_column_if_missing(conn, "nodes", "summary_hash", "TEXT")
    _add_column_if_missing(conn, "nodes", "deleted_at", "INTEGER")
    _add_column_if_missing(conn, "nodes", "file_mtime", "REAL")
    _add_column_if_missing(conn, "nodes", "token_count", "INTEGER")
    # Multi-agent authorship — added in 0.5.0
    _add_column_if_missing(conn, "nodes", "summary_author", "TEXT")
    _add_column_if_missing(conn, "nodes", "summary_session", "TEXT")
    # Index on deleted_at must be created after the column migration
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes(deleted_at)")
    # node_visits table — added in 0.4.3
    conn.execute("""CREATE TABLE IF NOT EXISTS node_visits (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT    NOT NULL,
        node_id     TEXT    NOT NULL,
        tool        TEXT    NOT NULL,
        visited_at  INTEGER NOT NULL
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_visits_session ON node_visits(session_id, visited_at DESC)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_visits_node ON node_visits(node_id)")
    conn.commit()


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
