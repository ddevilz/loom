from __future__ import annotations

import sqlite3
from pathlib import Path

_FTS5_PROBE = "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x);"
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


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


_DDL_CORE, _DDL_FTS5 = _load_schema()


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, col: str, typedef: str
) -> None:
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
    # Index on deleted_at must be created after the column migration
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes(deleted_at)"
    )
    conn.commit()
