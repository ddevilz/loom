"""Tests for composed Repository facade and remaining sub-repositories.

Covers:
- SearchRepository.search / find_replacements
- TraversalRepository.neighbors / blast_radius / stats
- ContextRepository.build_primer / get_context_packet (brief)
- Repository composed facade — all 7 sub-repos attached
"""
from __future__ import annotations

import pytest

from loom.graph.db import DB
from loom.graph.models import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.graph.repository import Repository
from loom.graph.repository.context import ContextRepository
from loom.graph.repository.search import SearchRepository
from loom.graph.repository.traversal import TraversalRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db() -> DB:
    db = DB(path=":memory:")
    db.connect()
    return db


def _node(name: str, path: str = "src/mod.py", kind: NodeKind = NodeKind.FUNCTION) -> Node:
    return Node(
        id=f"{kind.value}:{path}:{name}",
        kind=kind,
        source=NodeSource.CODE,
        name=name,
        path=path,
    )


def _edge(from_id: str, to_id: str, kind: EdgeType = EdgeType.CALLS) -> Edge:
    return Edge(from_id=from_id, to_id=to_id, kind=kind)


# ---------------------------------------------------------------------------
# Repository composed facade
# ---------------------------------------------------------------------------


def test_repository_all_sub_repos_attached():
    db = _make_db()
    repo = Repository(db)
    assert repo.nodes is not None
    assert repo.edges is not None
    assert repo.search is not None
    assert repo.traversal is not None
    assert repo.context is not None
    assert repo.sessions is not None
    assert repo.analytics is not None


def test_repository_sub_repos_share_db():
    """All sub-repos should hold the same DB instance."""
    db = _make_db()
    repo = Repository(db)
    # Upsert via nodes sub-repo, read back via search sub-repo
    node = _node("shared_fn")
    repo.nodes.upsert([node])
    results = repo.search.search("shared_fn")
    assert len(results) == 1
    assert results[0].node.name == "shared_fn"


# ---------------------------------------------------------------------------
# SearchRepository
# ---------------------------------------------------------------------------


class TestSearchRepository:
    def test_search_returns_matching_nodes(self):
        db = _make_db()
        repo = SearchRepository(db)
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        nodes_repo.upsert([_node("authenticate"), _node("authorize")])

        # Search for full name — works for both FTS5 and LIKE
        results = repo.search("authenticate")
        assert len(results) >= 1
        assert any(r.node.name == "authenticate" for r in results)

    def test_search_empty_db(self):
        db = _make_db()
        repo = SearchRepository(db)
        results = repo.search("anything")
        assert results == []

    def test_search_limit(self):
        db = _make_db()
        repo = SearchRepository(db)
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        nodes_repo.upsert([_node(f"fn_{i}") for i in range(10)])

        results = repo.search("fn_", limit=3)
        assert len(results) <= 3

    def test_find_replacements_no_node(self):
        db = _make_db()
        repo = SearchRepository(db)
        # Non-existent node — should return []
        candidates = repo.find_replacements("nonexistent::id")
        assert candidates == []

    def test_find_replacements_returns_live_callee_siblings(self):
        db = _make_db()
        repo = SearchRepository(db)
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)

        dead = _node("dead_fn", path="src/dead.py")
        live_with_callers = _node("live_fn", path="src/dead.py")
        caller = _node("caller_fn", path="src/caller.py")
        nodes_repo.upsert([dead, live_with_callers, caller])
        edges_repo.upsert([_edge(caller.id, live_with_callers.id)])

        candidates = repo.find_replacements(dead.id)
        assert len(candidates) >= 1
        assert any(c.name == "live_fn" for c in candidates)


# ---------------------------------------------------------------------------
# TraversalRepository
# ---------------------------------------------------------------------------


class TestTraversalRepository:
    def _setup(self) -> tuple[DB, TraversalRepository]:
        db = _make_db()
        return db, TraversalRepository(db)

    def test_neighbors_empty(self):
        db, repo = self._setup()
        assert repo.neighbors("nonexistent") == []

    def test_neighbors_out_depth1(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        a, b, c = _node("a"), _node("b"), _node("c")
        nodes_repo.upsert([a, b, c])
        edges_repo.upsert([_edge(a.id, b.id), _edge(b.id, c.id)])

        result = repo.neighbors(a.id, depth=1, direction="out")
        names = {n.name for n in result}
        assert names == {"b"}

    def test_neighbors_out_depth2(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        a, b, c = _node("a"), _node("b"), _node("c")
        nodes_repo.upsert([a, b, c])
        edges_repo.upsert([_edge(a.id, b.id), _edge(b.id, c.id)])

        result = repo.neighbors(a.id, depth=2, direction="out")
        names = {n.name for n in result}
        assert names == {"b", "c"}

    def test_blast_radius_returns_callers(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        target = _node("target")
        caller1 = _node("caller1")
        caller2 = _node("caller2")
        nodes_repo.upsert([target, caller1, caller2])
        edges_repo.upsert([_edge(caller1.id, target.id), _edge(caller2.id, target.id)])

        nodes, total = repo.blast_radius(target.id, depth=1)
        assert total == 2
        assert len(nodes) == 2

    def test_blast_radius_empty(self):
        db, repo = self._setup()
        nodes, total = repo.blast_radius("no_such_node")
        assert total == 0
        assert nodes == []

    def test_stats_empty_db(self):
        db, repo = self._setup()
        s = repo.stats()
        assert s["total_nodes"] == 0
        assert s["total_edges"] == 0

    def test_stats_counts(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        a, b = _node("a"), _node("b")
        nodes_repo.upsert([a, b])
        edges_repo.upsert([_edge(a.id, b.id)])

        s = repo.stats()
        assert s["total_nodes"] == 2
        assert s["total_edges"] == 1

    def test_community_members_empty(self):
        db, repo = self._setup()
        assert repo.community_members("nonexistent_community") == []

    def test_shortest_path_none_when_no_path(self):
        db, repo = self._setup()
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        a, b = _node("a"), _node("b")
        nodes_repo.upsert([a, b])
        # No edges — no path
        result = repo.shortest_path(a.id, b.id)
        assert result is None

    def test_god_nodes_empty(self):
        db, repo = self._setup()
        assert repo.god_nodes() == []

    def test_build_blast_radius_payload_structure(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        target = _node("target")
        caller = _node("caller")
        nodes_repo.upsert([target, caller])
        edges_repo.upsert([_edge(caller.id, target.id)])

        payload = repo.build_blast_radius_payload(target.id)
        assert payload["node_id"] == target.id
        assert payload["total"] == 1
        assert not payload["truncated"]
        assert len(payload["nodes"]) == 1
        assert payload["nodes"][0]["name"] == "caller"


# ---------------------------------------------------------------------------
# ContextRepository
# ---------------------------------------------------------------------------


class TestContextRepository:
    def _setup(self) -> tuple[DB, ContextRepository]:
        db = _make_db()
        return db, ContextRepository(db)

    def test_build_primer_empty_db(self):
        db, repo = self._setup()
        result = repo.build_primer()
        assert "not yet analyzed" in result

    def test_build_primer_empty_db_as_json(self):
        db, repo = self._setup()
        data = repo.build_primer(as_json=True)
        assert isinstance(data, dict)
        assert data.get("empty") is True

    def test_build_primer_with_nodes(self):
        db, repo = self._setup()
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        nodes_repo.upsert([_node("fn1", path="src/loom/auth/auth.py")])

        result = repo.build_primer()
        assert "function" in result or "fn" in result.lower() or "1" in result

    def test_get_context_packet_missing(self):
        db, repo = self._setup()
        assert repo.get_context_packet("nonexistent::id") is None

    def test_get_context_packet_brief(self):
        db, repo = self._setup()
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        node = _node("my_fn")
        nodes_repo.upsert([node])

        packet = repo.get_context_packet(node.id, brief=True)
        assert packet is not None
        assert packet["id"] == node.id
        assert packet["name"] == "my_fn"
        # Brief packet has no callers/callees keys
        assert "callers" not in packet

    def test_get_context_packet_full_function(self):
        db, repo = self._setup()
        from loom.graph.repository.edges import EdgeRepository
        from loom.graph.repository.nodes import NodeRepository

        nodes_repo = NodeRepository(db)
        edges_repo = EdgeRepository(db)
        target = _node("target_fn")
        caller = _node("caller_fn")
        nodes_repo.upsert([target, caller])
        edges_repo.upsert([_edge(caller.id, target.id)])

        packet = repo.get_context_packet(target.id)
        assert packet is not None
        assert packet["kind"] == "function"
        assert "callers" in packet
        assert packet["callers_total"] == 1
