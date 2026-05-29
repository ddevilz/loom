"""Unit tests for GraphTagger — dead-code, entry-point, hub, bridge tags."""

from __future__ import annotations

import time

import pytest

from loom.graph.db import DB
from loom.graph.repository import Repository
from loom.indexer.graph_tagger import compute_graph_tags

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_node(db: DB, node_id: str, kind: str = "function", name: str = "func") -> None:
    """Insert a minimal node row directly into the DB."""
    conn = db.connect()
    conn.execute(
        "INSERT OR IGNORE INTO nodes "
        "(id, kind, source, name, path, language, content_hash, updated_at) "
        "VALUES (?, ?, 'code', ?, 'src/foo.py', 'python', 'abc123', ?)",
        (node_id, kind, name, int(time.time())),
    )
    conn.commit()


def _insert_edge(db: DB, from_id: str, to_id: str, kind: str = "CALLS") -> None:
    """Insert a minimal edge row directly into the DB."""
    conn = db.connect()
    conn.execute(
        "INSERT OR IGNORE INTO edges (from_id, to_id, kind, confidence) VALUES (?, ?, ?, ?)",
        (from_id, to_id, kind, 1.0),
    )
    conn.commit()


@pytest.fixture
def repo(tmp_path):
    """Repository backed by a real in-memory DB."""
    db = DB(path=":memory:")
    db.connect()  # initialise schema
    return Repository(db)


# ---------------------------------------------------------------------------
# Test 1: dead-code tag
# ---------------------------------------------------------------------------


def test_dead_code_tag_zero_indegree_no_decorator(repo: Repository) -> None:
    """Node with zero CALLS in-degree and no entry-facing decorator tags gets 'dead-code'."""
    node_id = "function:repo:src/foo.py:orphan"
    _insert_node(repo.db, node_id, name="orphan")

    result = compute_graph_tags(repo)

    assert node_id in result
    assert "dead-code" in result[node_id]


# ---------------------------------------------------------------------------
# Test 2: entry-point tag (not dead-code)
# ---------------------------------------------------------------------------


def test_entry_point_tag_zero_indegree_with_decorator(repo: Repository) -> None:
    """Node with zero CALLS in-degree + 'api-endpoint' tag gets 'entry-point', NOT 'dead-code'."""
    node_id = "function:repo:src/views.py:create_user"
    _insert_node(repo.db, node_id, name="create_user")
    repo.tags.add_tags(node_id, ["api-endpoint"])

    result = compute_graph_tags(repo)

    assert node_id in result
    assert "entry-point" in result[node_id]
    assert "dead-code" not in result[node_id]


# ---------------------------------------------------------------------------
# Test 3: hub tag
# ---------------------------------------------------------------------------


def test_hub_tag_high_indegree(repo: Repository) -> None:
    """Node with in-degree > mean + 2σ gets 'hub' tag."""
    # Create 10 callers → hub, plus many nodes with 0 in-degree to push mean low
    hub_id = "function:repo:src/utils.py:shared_helper"
    _insert_node(repo.db, hub_id, name="shared_helper")

    # Create 10 caller nodes, each calls hub_id
    for i in range(10):
        caller_id = f"function:repo:src/caller{i}.py:fn{i}"
        _insert_node(repo.db, caller_id, name=f"fn{i}")
        _insert_edge(repo.db, caller_id, hub_id)

    # Create 5 more isolated nodes (0 in-degree) to keep mean low
    for i in range(5):
        isolated_id = f"function:repo:src/isolated{i}.py:iso{i}"
        _insert_node(repo.db, isolated_id, name=f"iso{i}")

    result = compute_graph_tags(repo)

    assert hub_id in result
    assert "hub" in result[hub_id]


# ---------------------------------------------------------------------------
# Test 4: bridge tag
# ---------------------------------------------------------------------------


def test_bridge_tag_high_in_and_out_degree(repo: Repository) -> None:
    """Node with in_deg > 3 AND out_deg > 3 gets 'bridge' tag."""
    bridge_id = "function:repo:src/bridge.py:bridge_fn"
    _insert_node(repo.db, bridge_id, name="bridge_fn")

    # 4 callers → bridge (in_deg = 4 > BRIDGE_MIN_INDEGREE = 3)
    for i in range(4):
        caller_id = f"function:repo:src/c{i}.py:caller{i}"
        _insert_node(repo.db, caller_id, name=f"caller{i}")
        _insert_edge(repo.db, caller_id, bridge_id)

    # 4 callees → bridge calls them (out_deg = 4 > BRIDGE_MIN_OUTDEGREE = 3)
    for i in range(4):
        callee_id = f"function:repo:src/d{i}.py:callee{i}"
        _insert_node(repo.db, callee_id, name=f"callee{i}")
        _insert_edge(repo.db, bridge_id, callee_id)

    result = compute_graph_tags(repo)

    assert bridge_id in result
    assert "bridge" in result[bridge_id]


# ---------------------------------------------------------------------------
# Test 5: non-dead node (has callers)
# ---------------------------------------------------------------------------


def test_no_dead_code_tag_when_node_has_callers(repo: Repository) -> None:
    """Node with at least one CALLS in-degree does NOT get 'dead-code'."""
    callee_id = "function:repo:src/foo.py:reachable"
    caller_id = "function:repo:src/bar.py:caller"
    _insert_node(repo.db, callee_id, name="reachable")
    _insert_node(repo.db, caller_id, name="caller")
    _insert_edge(repo.db, caller_id, callee_id)

    result = compute_graph_tags(repo)

    tags_for_callee = result.get(callee_id, [])
    assert "dead-code" not in tags_for_callee


# ---------------------------------------------------------------------------
# Test 6: hub threshold — moderate in-degree nodes don't get hub
# ---------------------------------------------------------------------------


def test_hub_threshold_moderate_indegree_not_hub(repo: Repository) -> None:
    """Node with moderate in-degree (below mean + 2σ) does NOT get 'hub'."""
    # 10 nodes each with in-degree 1 → mean=1, stdev≈0, threshold≈1
    # A node with exactly 1 in-degree should NOT be a hub (must be > threshold)
    nodes = []
    for i in range(10):
        n_id = f"function:repo:src/m{i}.py:mod{i}"
        _insert_node(repo.db, n_id, name=f"mod{i}")
        nodes.append(n_id)

    # Give each node exactly 1 caller from a "ghost" caller node
    for i, n_id in enumerate(nodes):
        caller_id = f"function:repo:src/ghost{i}.py:ghost{i}"
        _insert_node(repo.db, caller_id, name=f"ghost{i}")
        _insert_edge(repo.db, caller_id, n_id)

    result = compute_graph_tags(repo)

    # None of the uniform in-degree-1 nodes should be a hub
    for n_id in nodes:
        tags = result.get(n_id, [])
        assert "hub" not in tags, f"{n_id} unexpectedly got hub tag"


# ---------------------------------------------------------------------------
# Test 7: empty graph — returns empty dict, no crash
# ---------------------------------------------------------------------------


def test_empty_graph_returns_empty_dict(repo: Repository) -> None:
    """With no nodes, compute_graph_tags returns an empty dict without raising."""
    result = compute_graph_tags(repo)
    assert result == {}


# ---------------------------------------------------------------------------
# Test 8: entry-point with async-task decorator tag
# ---------------------------------------------------------------------------


def test_entry_point_async_task_tag(repo: Repository) -> None:
    """Node with 'async-task' decorator tag + zero in-degree gets 'entry-point'."""
    node_id = "function:repo:src/tasks.py:send_email"
    _insert_node(repo.db, node_id, name="send_email")
    repo.tags.add_tags(node_id, ["async-task"])

    result = compute_graph_tags(repo)

    assert "entry-point" in result.get(node_id, [])
    assert "dead-code" not in result.get(node_id, [])


# ---------------------------------------------------------------------------
# Test 9: bridge requires BOTH in-deg AND out-deg > threshold (not just one)
# ---------------------------------------------------------------------------


def test_bridge_brandes_structural(repo: Repository) -> None:
    """A node that lies on many shortest paths is a bridge under Brandes betweenness.

    With 4 callers and 2 callees, the node IS on shortest paths between those groups
    and correctly gets the 'bridge' tag. (Old degree heuristic required both in & out
    degree > threshold; Brandes uses actual path-betweenness instead.)
    """
    high_in_only = "function:repo:src/popular.py:popular_fn"
    _insert_node(repo.db, high_in_only, name="popular_fn")

    # 4 callers (high betweenness: all paths from callers to callees go through this node)
    for i in range(4):
        caller_id = f"function:repo:src/caller_b{i}.py:cbfn{i}"
        _insert_node(repo.db, caller_id, name=f"cbfn{i}")
        _insert_edge(repo.db, caller_id, high_in_only)

    # 2 callees — Brandes still marks this as bridge (it's on all 4*2=8 shortest paths)
    for i in range(2):
        callee_id = f"function:repo:src/callee_b{i}.py:cbee{i}"
        _insert_node(repo.db, callee_id, name=f"cbee{i}")
        _insert_edge(repo.db, high_in_only, callee_id)

    result = compute_graph_tags(repo)

    # With Brandes, this node has high betweenness → gets bridge tag
    tags = result.get(high_in_only, [])
    assert "bridge" in tags


# ---------------------------------------------------------------------------
# Test 10: deleted nodes excluded from graph stats
# ---------------------------------------------------------------------------


def test_deleted_nodes_excluded_from_tags(repo: Repository) -> None:
    """Nodes with deleted_at set should not appear in any computed tags."""
    live_id = "function:repo:src/live.py:live_fn"
    dead_id = "function:repo:src/deleted.py:dead_fn"
    _insert_node(repo.db, live_id, name="live_fn")
    _insert_node(repo.db, dead_id, name="dead_fn")

    # Soft-delete dead_id
    conn = repo.db.connect()
    conn.execute(
        "UPDATE nodes SET deleted_at = ? WHERE id = ?",
        (int(time.time()), dead_id),
    )
    conn.commit()

    result = compute_graph_tags(repo)

    # deleted node should not appear in result at all
    assert dead_id not in result
    # live node is still present (may get dead-code tag)
    assert live_id in result


# ---------------------------------------------------------------------------
# Test 11: TESTED_BY edge does NOT suppress dead-code
# ---------------------------------------------------------------------------


def test_tested_by_edge_does_not_suppress_dead_code(tmp_path):
    """A node with a TESTED_BY edge but zero CALLS in-degree is still dead-code."""
    db = DB(path=tmp_path / "test.db")
    db.connect()  # initialise schema
    repo = Repository(db)

    prod_id = "function:repo:src/validate.py:validate"
    test_id = "function:repo:tests/test_validate.py:test_validate"
    _insert_node(db, prod_id, "function", "validate")
    _insert_node(db, test_id, "function", "test_validate")
    # TESTED_BY edge from test to prod
    conn = db.connect()
    conn.execute(
        "INSERT INTO edges (from_id, to_id, kind, confidence) VALUES (?,?,?,?)",
        (test_id, prod_id, "TESTED_BY", 0.7),
    )
    conn.commit()

    result = compute_graph_tags(repo)
    # prod node has zero CALLS in-degree → still dead-code (TESTED_BY doesn't count)
    assert "dead-code" in result.get(prod_id, [])
