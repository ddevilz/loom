"""Unit tests for tag search — parse_tag_query() and SearchRepository tag filtering."""

from __future__ import annotations

from loom.graph.db import DB
from loom.graph.models import Node, NodeKind, NodeSource
from loom.graph.repository import Repository
from loom.graph.repository.search import parse_tag_query

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> DB:
    db = DB(path=":memory:")
    db.connect()
    return db


def _make_node(name: str, path: str = "src/foo.py") -> Node:
    return Node(
        id=f"function:{path}:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
    )


# ---------------------------------------------------------------------------
# parse_tag_query tests
# ---------------------------------------------------------------------------


def test_parse_tag_query_single_tag() -> None:
    """tag:auth login → (["auth"], "login")"""
    tags, fts = parse_tag_query("tag:auth login")
    assert tags == ["auth"]
    assert fts == "login"


def test_parse_tag_query_multiple_tags() -> None:
    """tag:auth tag:api-endpoint → (["auth", "api-endpoint"], "")"""
    tags, fts = parse_tag_query("tag:auth tag:api-endpoint")
    assert tags == ["auth", "api-endpoint"]
    assert fts == ""


def test_parse_tag_query_no_tags() -> None:
    """validate token → ([], "validate token")"""
    tags, fts = parse_tag_query("validate token")
    assert tags == []
    assert fts == "validate token"


# ---------------------------------------------------------------------------
# SearchRepository tag filter tests
# ---------------------------------------------------------------------------


def test_search_single_tag_filter() -> None:
    """Node with tag 'auth' is returned when searching tag:auth."""
    db = _make_db()
    repo = Repository(db)

    node = _make_node("validate_token")
    repo.nodes.upsert([node])
    repo.tags.add_tags(node.id, ["auth"])

    results = repo.search.search("tag:auth", limit=10)
    ids = [r.node.id for r in results]
    assert node.id in ids


def test_search_tag_excludes_untagged_node() -> None:
    """Node without tag 'auth' is not returned when searching tag:auth."""
    db = _make_db()
    repo = Repository(db)

    tagged = _make_node("tagged_fn", "src/a.py")
    untagged = _make_node("untagged_fn", "src/b.py")
    repo.nodes.upsert([tagged, untagged])
    repo.tags.add_tags(tagged.id, ["auth"])

    results = repo.search.search("tag:auth", limit=10)
    ids = [r.node.id for r in results]
    assert tagged.id in ids
    assert untagged.id not in ids


def test_search_multi_tag_and_filter() -> None:
    """Only node with BOTH 'auth' AND 'orm' tags matches tag:auth tag:orm."""
    db = _make_db()
    repo = Repository(db)

    both = _make_node("both_tags_fn", "src/both.py")
    auth_only = _make_node("auth_only_fn", "src/auth.py")
    repo.nodes.upsert([both, auth_only])
    repo.tags.add_tags(both.id, ["auth", "orm"])
    repo.tags.add_tags(auth_only.id, ["auth"])

    results = repo.search.search("tag:auth tag:orm", limit=10)
    ids = [r.node.id for r in results]
    assert both.id in ids
    assert auth_only.id not in ids


def test_search_tag_plus_text() -> None:
    """Node with tag 'auth' and name containing 'validate' matches 'tag:auth validate'."""
    db = _make_db()
    repo = Repository(db)

    match_node = _make_node("validate_user", "src/auth.py")
    other_node = _make_node("process_payment", "src/payment.py")
    repo.nodes.upsert([match_node, other_node])
    repo.tags.add_tags(match_node.id, ["auth"])
    repo.tags.add_tags(other_node.id, ["auth"])

    results = repo.search.search("tag:auth validate", limit=10)
    ids = [r.node.id for r in results]
    # match_node has tag auth AND name contains "validate"
    assert match_node.id in ids
    # other_node has tag auth but name doesn't contain "validate"
    assert other_node.id not in ids


def test_search_tag_returns_score_one_when_no_fts_text() -> None:
    """Tag-only search returns score=1.0 for all results."""
    db = _make_db()
    repo = Repository(db)

    node = _make_node("some_fn")
    repo.nodes.upsert([node])
    repo.tags.add_tags(node.id, ["dead-code"])

    results = repo.search.search("tag:dead-code", limit=10)
    assert len(results) >= 1
    for r in results:
        assert r.score == 1.0
