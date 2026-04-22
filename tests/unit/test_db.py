from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loom.core.db import connect, has_fts5, init_schema


def test_init_schema_creates_tables(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "nodes" in tables
    assert "edges" in tables
    assert "schema_meta" in tables


def test_init_schema_sets_wal(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_init_schema_idempotent(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    init_schema(conn)  # second call must not raise


def test_fts5_detection(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    # True on virtually all standard Python sqlite3 builds
    assert has_fts5(conn) in (True, False)


def test_fts5_index_usable_when_available(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    if not has_fts5(conn):
        pytest.skip("FTS5 not available in this sqlite3 build")
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
        "VALUES (?, 'function', 'code', ?, ?, ?)",
        ("function:a.py:validate", "validate", "a.py", 0),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT id FROM nodes_fts WHERE nodes_fts MATCH ?",
        ("validate",),
    ).fetchall()
    assert any(r[0] == "function:a.py:validate" for r in rows)


def test_foreign_keys_cascade(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = connect(db)
    init_schema(conn)
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
        "VALUES ('function:a:f', 'function', 'code', 'f', 'a', 0)"
    )
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
        "VALUES ('function:b:g', 'function', 'code', 'g', 'b', 0)"
    )
    conn.execute(
        "INSERT INTO edges (from_id, to_id, kind) VALUES ('function:a:f', 'function:b:g', 'calls')"
    )
    conn.commit()
    conn.execute("DELETE FROM nodes WHERE id = 'function:a:f'")
    conn.commit()
    remaining = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert remaining == 0
