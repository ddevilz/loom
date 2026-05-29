import sqlite3
from pathlib import Path

from loom.graph.db import DB


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_v062_columns_added(tmp_path: Path) -> None:
    db = DB(path=str(tmp_path / "loom.db"))
    conn = db.connect()

    assert "description" in _columns(conn, "edges")
    assert "language_notes" in _columns(conn, "nodes")
    assert "layer" in _columns(conn, "nodes")
    assert "bridge_score" in _columns(conn, "nodes")


def test_v062_migration_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "loom.db"
    db1 = DB(path=str(db_path))
    db1.connect()

    # Second connect: must not raise
    db2 = DB(path=str(db_path))
    conn = db2.connect()
    assert "bridge_score" in _columns(conn, "nodes")
