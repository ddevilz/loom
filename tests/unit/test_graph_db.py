from loom.graph.db import DB, connect, has_fts5, init_schema, resolve_db_path


def test_connect_memory():
    conn = connect(":memory:")
    assert conn is not None


def test_init_schema_memory():
    conn = connect(":memory:")
    init_schema(conn)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "nodes" in tables
    assert "edges" in tables


def test_db_class():
    db = DB(path=":memory:")
    conn = db.connect()
    assert conn is not None
