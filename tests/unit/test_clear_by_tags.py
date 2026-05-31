from pathlib import Path

from loom.graph.db import DB
from loom.graph.repository.tags import TagRepository

_TS = "2024-01-01T00:00:00"


def _seed_node(db: DB, node_id: str) -> None:
    with db._lock:
        conn = db.connect()
        conn.execute(
            "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
            "VALUES (?, 'function', 'code', 'f', 'x.py', ?)",
            (node_id, _TS),
        )
        conn.commit()


def test_clear_by_tags_removes_only_named(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    _seed_node(db, "function:r:x.py:f")
    tr = TagRepository(db)
    tr.add_tags("function:r:x.py:f", ["hub", "bridge", "auth"], source="system")
    tr.clear_by_tags(["hub", "bridge"], source="system")
    remaining = set(tr.get_tags("function:r:x.py:f"))
    assert "auth" in remaining
    assert "hub" not in remaining
    assert "bridge" not in remaining


def test_clear_by_tags_rebuilds_tags_normalized(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    _seed_node(db, "function:r:y.py:g")
    tr = TagRepository(db)
    tr.add_tags("function:r:y.py:g", ["hub", "service"], source="system")
    tr.clear_by_tags(["hub"], source="system")
    with db._lock:
        conn = db.connect()
        row = conn.execute(
            "SELECT tags_normalized FROM nodes WHERE id = ?", ("function:r:y.py:g",)
        ).fetchone()
    norm = row["tags_normalized"] or ""
    assert "hub" not in norm.split()
    assert "service" in norm.split()


def test_clear_by_tags_returns_count(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    _seed_node(db, "function:r:z.py:h")
    tr = TagRepository(db)
    tr.add_tags("function:r:z.py:h", ["hub", "bridge"], source="system")
    deleted = tr.clear_by_tags(["hub", "bridge"], source="system")
    assert deleted == 2


def test_clear_by_tags_empty_list_noop(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    tr = TagRepository(db)
    deleted = tr.clear_by_tags([], source="system")
    assert deleted == 0
