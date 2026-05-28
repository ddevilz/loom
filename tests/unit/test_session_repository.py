"""Tests for SessionRepository."""

from __future__ import annotations

from loom.graph.db import DB
from loom.graph.models import Node, NodeKind, NodeSource
from loom.graph.repository.nodes import NodeRepository
from loom.graph.repository.sessions import SessionRepository


def _make_db():
    db = DB(path=":memory:")
    db.connect()
    return db


def test_create_and_get():
    db = _make_db()
    repo = SessionRepository(db)
    session = repo.create("claude-code")
    assert "session_id" in session
    fetched = repo.get(session["session_id"])
    assert fetched is not None
    assert fetched["agent_id"] == "claude-code"


def test_get_latest_for_agent():
    db = _make_db()
    repo = SessionRepository(db)
    repo.create("claude-code")
    s2 = repo.create("claude-code")
    latest = repo.get_latest_for_agent("claude-code")
    assert latest["id"] == s2["session_id"]


def test_record_visit():
    db = _make_db()
    node_repo = NodeRepository(db)
    node = Node(
        id="function:a.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="a.py",
    )
    node_repo.upsert([node])
    sess_repo = SessionRepository(db)
    s = sess_repo.create("test")
    sess_repo.record_visit(s["session_id"], node.id, "get_context")
    gaps = sess_repo.get_unannotated_reads(s["session_id"])
    assert len(gaps) >= 1
    assert gaps[0]["node_id"] == node.id


def test_prune():
    db = _make_db()
    repo = SessionRepository(db)
    for i in range(25):
        repo.create(f"agent-{i % 2}")
    deleted = repo.prune(keep=5)
    assert deleted > 0
