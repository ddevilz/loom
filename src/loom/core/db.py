from __future__ import annotations

import sqlite3
from pathlib import Path

_FTS5_PROBE = "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(x);"


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


_DDL_CORE = """
CREATE TABLE IF NOT EXISTS nodes (
    id              TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    source          TEXT NOT NULL,
    name            TEXT NOT NULL,
    path            TEXT NOT NULL,
    start_line      INTEGER,
    end_line        INTEGER,
    language        TEXT,
    content_hash    TEXT,
    file_hash       TEXT,
    file_mtime      REAL,
    summary         TEXT,
    summary_hash    TEXT,
    is_dead_code    INTEGER NOT NULL DEFAULT 0,
    community_id    TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}',
    updated_at      INTEGER NOT NULL,
    deleted_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_lang ON nodes(language);

CREATE TABLE IF NOT EXISTS edges (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id          TEXT NOT NULL,
    to_id            TEXT NOT NULL,
    kind             TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 1.0,
    confidence_tier  TEXT NOT NULL DEFAULT 'extracted',
    metadata         TEXT NOT NULL DEFAULT '{}',
    UNIQUE(from_id, to_id, kind)
);
CREATE INDEX IF NOT EXISTS idx_edges_from      ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to        ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind      ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_to_kind   ON edges(to_id, kind);
CREATE INDEX IF NOT EXISTS idx_edges_from_kind ON edges(from_id, kind);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT 'default',
    started_at  INTEGER NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at DESC);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_DDL_FTS5 = """
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, name, summary, path,
    content='nodes', content_rowid='rowid',
    tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
    INSERT INTO nodes_fts(rowid, id, name, summary, path)
    VALUES (new.rowid, new.id, new.name, new.summary, new.path);
END;
CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, name, summary, path)
    VALUES ('delete', old.rowid, old.id, old.name, old.summary, old.path);
END;
CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
    INSERT INTO nodes_fts(nodes_fts, rowid, id, name, summary, path)
    VALUES ('delete', old.rowid, old.id, old.name, old.summary, old.path);
    INSERT INTO nodes_fts(rowid, id, name, summary, path)
    VALUES (new.rowid, new.id, new.name, new.summary, new.path);
END;
"""


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
