from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

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


def _derive_repo_name() -> str:
    # Try git remote origin
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        # Strip .git suffix, extract last path component
        name = url.rstrip("/")
        if name.endswith(".git"):
            name = name[:-4]
        name = name.rstrip("/")
        name = name.split("/")[-1].split(":")[-1]
        if name:
            return name
    except Exception:
        pass
    # Fallback: git root directory name
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        return Path(root).name
    except Exception:
        pass
    return "unknown"


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
    # v0.6.1 new columns
    _add_column_if_missing(conn, "nodes", "complexity", "TEXT")
    _add_column_if_missing(conn, "nodes", "tags_normalized", "TEXT DEFAULT ''")
    # v0.6.2 new columns
    _add_column_if_missing(conn, "edges", "description", "TEXT")
    _add_column_if_missing(conn, "nodes", "language_notes", "TEXT")
    _add_column_if_missing(conn, "nodes", "layer", "TEXT")
    _add_column_if_missing(conn, "nodes", "bridge_score", "REAL")
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
    # v0.6.1 new tables (idempotent via IF NOT EXISTS)
    conn.execute("""CREATE TABLE IF NOT EXISTS file_fingerprints (
        file_path    TEXT PRIMARY KEY,
        content_sha  TEXT NOT NULL,
        mtime_ns     INTEGER NOT NULL,
        indexed_at   REAL NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS node_tags (
        node_id  TEXT NOT NULL,
        tag      TEXT NOT NULL,
        source   TEXT NOT NULL DEFAULT 'system',
        UNIQUE(node_id, tag, source)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tags_tag  ON node_tags(tag, node_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_node_tags_node ON node_tags(node_id)")
    # v0.6.1 EdgeType uppercase migration
    conn.execute("UPDATE edges SET kind = UPPER(kind) WHERE kind != UPPER(kind)")
    # v0.6.1 repo_name in meta (for 4-part node ID migration)
    existing = conn.execute("SELECT value FROM meta WHERE key = 'repo_name'").fetchone()
    if not existing:
        repo_name = _derive_repo_name()
        conn.execute("INSERT OR IGNORE INTO meta VALUES ('repo_name', ?)", (repo_name,))
    # v0.6.1 migrate 3-part IDs to 4-part (idempotent: skip already-migrated IDs)
    # Ensure parent_id column exists before migration
    _add_column_if_missing(conn, "nodes", "parent_id", "TEXT")
    repo_name = conn.execute("SELECT value FROM meta WHERE key = 'repo_name'").fetchone()[0]
    # Migrate non-file 3-part IDs (kind:path:symbol → kind:repo:path:symbol, 2 colons → 3 colons).
    # File nodes are already "complete" at 3 parts (file:repo:path), so exclude them.
    conn.execute(
        """
        UPDATE nodes SET id = kind || ':' || ? || ':' || substr(id, instr(id, ':') + 1)
        WHERE kind != 'file'
          AND (length(id) - length(replace(id, ':', ''))) = 2
    """,
        (repo_name,),
    )
    # Migrate 2-part IDs (file:path → file:repo:path, 1 colon → 2 colons)
    conn.execute(
        """
        UPDATE nodes SET id = kind || ':' || ? || ':' || substr(id, instr(id, ':') + 1)
        WHERE (length(id) - length(replace(id, ':', ''))) = 1
    """,
        (repo_name,),
    )
    # Migrate parent_id non-file 3-part → 4-part
    conn.execute(
        """
        UPDATE nodes SET parent_id = (
            substr(parent_id, 1, instr(parent_id, ':') - 1) || ':' || ? || ':' ||
            substr(parent_id, instr(parent_id, ':') + 1)
        ) WHERE parent_id IS NOT NULL
          AND substr(parent_id, 1, instr(parent_id, ':') - 1) != 'file'
          AND (length(parent_id) - length(replace(parent_id, ':', ''))) = 2
    """,
        (repo_name,),
    )
    # Migrate parent_id 2-part → 3-part
    conn.execute(
        """
        UPDATE nodes SET parent_id = (
            substr(parent_id, 1, instr(parent_id, ':') - 1) || ':' || ? || ':' ||
            substr(parent_id, instr(parent_id, ':') + 1)
        ) WHERE parent_id IS NOT NULL
          AND (length(parent_id) - length(replace(parent_id, ':', ''))) = 1
    """,
        (repo_name,),
    )
    # v0.6.1 remove is_dead_code column (replaced by "dead-code" tag)
    if sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning(
            "SQLite %s does not support DROP COLUMN (requires 3.35.0+); "
            "is_dead_code column left in place",
            sqlite3.sqlite_version,
        )
    else:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("ALTER TABLE nodes DROP COLUMN is_dead_code")
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

    def get_repo_name(self) -> str:
        """Return the repo name stored in the meta table (set during init_schema)."""
        conn = self.connect()
        row = conn.execute("SELECT value FROM meta WHERE key = 'repo_name'").fetchone()
        return row[0] if row else "unknown"
