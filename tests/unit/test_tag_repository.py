"""Unit tests for TagRepository."""

import time

import pytest

from loom.graph.db import DB
from loom.graph.repository.tags import TagRepository


@pytest.fixture
def db_with_node(tmp_path):
    db = DB(tmp_path / "test.db")
    conn = db.connect()
    conn.execute(
        "INSERT INTO nodes (id, kind, source, name, path, updated_at)"
        " VALUES ('function:repo:src/foo.py:bar', 'function', 'code', 'bar', 'src/foo.py', ?)",
        (int(time.time()),),
    )
    conn.commit()
    return db


@pytest.fixture
def repo(db_with_node):
    return TagRepository(db_with_node)


NODE_ID = "function:repo:src/foo.py:bar"


def test_get_tags_empty(repo):
    assert repo.get_tags(NODE_ID) == []


def test_add_and_get_tags(repo):
    repo.add_tags(NODE_ID, ["auth", "api-endpoint"])
    tags = repo.get_tags(NODE_ID)
    assert "auth" in tags
    assert "api-endpoint" in tags


def test_add_tags_deduplicates(repo):
    repo.add_tags(NODE_ID, ["auth", "auth"])
    assert repo.get_tags(NODE_ID).count("auth") == 1


def test_add_tags_updates_normalized(repo, db_with_node):
    repo.add_tags(NODE_ID, ["auth", "web"])
    conn = db_with_node.connect()
    row = conn.execute("SELECT tags_normalized FROM nodes WHERE id = ?", (NODE_ID,)).fetchone()
    normalized = row[0]
    assert "auth" in normalized
    assert "web" in normalized


def test_agent_tags_survive_system_clear(repo):
    repo.add_tags(NODE_ID, ["security-sensitive"], source="agent")
    repo.add_tags(NODE_ID, ["api-endpoint"], source="system")
    repo.clear_node_tags(NODE_ID, source="system")
    tags = repo.get_tags(NODE_ID)
    assert "security-sensitive" in tags
    assert "api-endpoint" not in tags


def test_remove_tags(repo):
    repo.add_tags(NODE_ID, ["auth", "web"])
    repo.remove_tags(NODE_ID, ["auth"])
    tags = repo.get_tags(NODE_ID)
    assert "auth" not in tags
    assert "web" in tags


def test_clear_bulk(repo):
    repo.add_tags(NODE_ID, ["auth"])
    repo.clear_bulk([NODE_ID], source="system")
    assert repo.get_tags(NODE_ID) == []


def test_same_tag_different_sources_coexist(repo):
    """Same tag from system and agent can both exist (UNIQUE is on node_id, tag, source)."""
    repo.add_tags(NODE_ID, ["auth"], source="system")
    repo.add_tags(NODE_ID, ["auth"], source="agent")
    tags = repo.get_tags(NODE_ID)
    assert tags.count("auth") == 1  # get_tags deduplicates
