from pathlib import Path

from loom.graph.db import DB
from loom.graph.repository.traversal import TraversalRepository

_TS = "2024-01-01T00:00:00"


def _insert_node(conn, node_id: str, path: str, layer: str | None = None) -> None:
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, updated_at, layer) "
        "VALUES (?, 'function', 'code', 'f', ?, ?, ?)",
        (node_id, path, _TS, layer),
    )


def test_get_layer_summary_empty(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    tr = TraversalRepository(db)
    assert tr.get_layer_summary() == []


def test_get_layer_summary_with_nodes(tmp_path: Path):
    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    with db._lock:
        conn = db.connect()
        _insert_node(conn, "function:r:src/api/x.py:f1", "src/api/x.py", "api")
        _insert_node(conn, "function:r:src/api/y.py:f2", "src/api/y.py", "api")
        _insert_node(conn, "function:r:src/services/s.py:f3", "src/services/s.py", "service")
        conn.commit()
    tr = TraversalRepository(db)
    summary = dict(tr.get_layer_summary())
    assert summary == {"api": 2, "service": 1}


def test_assign_and_store_layers_persists(tmp_path: Path):
    from loom.graph.repository import Repository
    from loom.intelligence.architecture import assign_and_store_layers

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    with db._lock:
        conn = db.connect()
        _insert_node(conn, "function:r:src/api/x.py:f", "src/api/x.py")
        conn.commit()
    repo = Repository(db)
    counts = assign_and_store_layers(repo, tmp_path)
    assert counts.get("api") == 1
    with db._lock:
        conn = db.connect()
        row = conn.execute(
            "SELECT layer FROM nodes WHERE id = ?", ("function:r:src/api/x.py:f",)
        ).fetchone()
    assert row["layer"] == "api"
