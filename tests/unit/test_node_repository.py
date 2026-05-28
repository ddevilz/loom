from loom.graph.db import DB
from loom.graph.models import Node, NodeKind, NodeSource
from loom.graph.repository.nodes import NodeRepository


def _make_db():
    db = DB(path=":memory:")
    db.connect()
    return db


def _make_node(name="foo", path="src/foo.py"):
    return Node(
        id=f"function:{path}:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
    )


def test_upsert_and_get():
    db = _make_db()
    repo = NodeRepository(db)
    node = _make_node()
    count = repo.upsert([node])
    assert count == 1
    result = repo.get(node.id)
    assert result is not None
    assert result.name == "foo"


def test_get_nonexistent():
    db = _make_db()
    repo = NodeRepository(db)
    assert repo.get("nonexistent") is None


def test_get_batch():
    db = _make_db()
    repo = NodeRepository(db)
    n1 = _make_node("a", "src/a.py")
    n2 = _make_node("b", "src/b.py")
    repo.upsert([n1, n2])
    results = repo.get_batch([n1.id, n2.id])
    assert len(results) == 2


def test_mark_deleted():
    db = _make_db()
    repo = NodeRepository(db)
    repo.upsert([_make_node()])
    count = repo.mark_deleted("src/foo.py")
    assert count >= 1
