"""Tests for EdgeRepository."""

from __future__ import annotations

from loom.graph.db import DB
from loom.graph.models import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.graph.repository.edges import EdgeRepository
from loom.graph.repository.nodes import NodeRepository


def _make_db():
    db = DB(path=":memory:")
    db.connect()
    return db


def _seed(db):
    node_repo = NodeRepository(db)
    n1 = Node(
        id="function:a.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="a.py",
    )
    n2 = Node(
        id="function:b.py:bar",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="bar",
        path="b.py",
    )
    node_repo.upsert([n1, n2])
    edge_repo = EdgeRepository(db)
    edge_repo.upsert([Edge(from_id=n1.id, to_id=n2.id, kind=EdgeType.CALLS)])
    return node_repo, edge_repo, n1, n2


def test_upsert_and_get():
    db = _make_db()
    _, edge_repo, n1, _ = _seed(db)
    edges = edge_repo.get_for_node(n1.id)
    assert len(edges) >= 1


def test_get_filtered_by_kind():
    db = _make_db()
    _, edge_repo, n1, _ = _seed(db)
    edges = edge_repo.get_for_node(n1.id, kind=EdgeType.CALLS)
    assert len(edges) == 1
    edges_none = edge_repo.get_for_node(n1.id, kind=EdgeType.CONTAINS)
    assert len(edges_none) == 0


def test_delete_for_path():
    db = _make_db()
    _, edge_repo, _, _ = _seed(db)
    deleted = edge_repo.delete_for_path("a.py")
    assert deleted >= 1
