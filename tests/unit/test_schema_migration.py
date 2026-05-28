"""Tests for schema migration idempotency and correctness."""
import pytest
import sqlite3
import tempfile
from pathlib import Path


def test_schema_creates_file_fingerprints_table(tmp_path):
    """file_fingerprints table created on init."""
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "file_fingerprints" in tables


def test_schema_creates_node_tags_table(tmp_path):
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "node_tags" in tables


def test_nodes_has_complexity_column(tmp_path):
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert "complexity" in cols


def test_nodes_has_tags_normalized_column(tmp_path):
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert "tags_normalized" in cols


def test_nodes_lacks_is_dead_code_column(tmp_path):
    """is_dead_code removed."""
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(nodes)").fetchall()}
    assert "is_dead_code" not in cols


def test_schema_init_idempotent(tmp_path):
    """Running init twice does not raise."""
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    db.connect()
    db._conn = None  # Force re-init
    db.connect()  # Should not raise


def test_meta_stores_repo_name(tmp_path):
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    row = conn.execute("SELECT value FROM meta WHERE key = 'repo_name'").fetchone()
    assert row is not None
    assert len(row[0]) > 0


def test_edge_uppercase_migration(tmp_path):
    """Edges with lowercase kind get migrated to uppercase."""
    from loom.graph.db import DB
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    # Insert a lowercase edge directly
    conn.execute("INSERT OR IGNORE INTO edges (from_id, to_id, kind) VALUES (?, ?, ?)",
                 ("a:b:c:d", "a:b:e:f", "calls"))
    conn.commit()
    db._conn = None
    conn = db.connect()  # Re-open triggers migration
    row = conn.execute("SELECT kind FROM edges WHERE from_id = 'a:b:c:d'").fetchone()
    assert row[0] == "CALLS"


def test_complexity_enum_values():
    from loom.graph.models.enums import Complexity
    assert Complexity.SIMPLE == "simple"
    assert Complexity.MODERATE == "moderate"
    assert Complexity.COMPLEX == "complex"


def test_edge_type_uppercase():
    from loom.graph.models.edge import EdgeType
    assert EdgeType.CALLS == "CALLS"
    assert EdgeType.CONTAINS == "CONTAINS"
    assert EdgeType.COUPLED_WITH == "COUPLED_WITH"
    assert EdgeType.TESTED_BY == "TESTED_BY"
