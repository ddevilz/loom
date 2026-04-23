from __future__ import annotations

import sqlite3

from loom.core.context import DB


def test_db_imports() -> None:
    db = DB(path=":memory:")
    assert db.path == ":memory:"
    assert db._conn is None


def test_db_connect_returns_connection() -> None:
    db = DB(path=":memory:")
    conn = db.connect()
    assert isinstance(conn, sqlite3.Connection)
    # Second call returns same connection
    assert db.connect() is conn


def test_db_fts5_flag_set_after_connect() -> None:
    db = DB(path=":memory:")
    db.connect()
    assert db._fts5 is not None  # True or False, but not None
