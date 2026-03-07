from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from loom.analysis.code.communities import _generate_community_name
from loom.analysis.code.communities import detect_communities


def test_generate_community_name_from_common_prefix():
    """Test that community name is generated from most common word."""
    names = ["auth_login", "auth_logout", "auth_validate", "auth_refresh"]
    result = _generate_community_name(names)
    assert result == "auth"


def test_generate_community_name_mixed_words():
    """Test community naming with mixed function names."""
    names = ["validate_user", "validate_token", "check_auth", "validate_session"]
    result = _generate_community_name(names)
    assert result == "validate"


def test_generate_community_name_single_word_functions():
    """Test community naming with single-word function names."""
    names = ["login", "logout", "authenticate"]
    result = _generate_community_name(names)
    # Should pick the most common single word
    assert result in ["login", "logout", "authenticate"]


def test_generate_community_name_empty_list():
    """Test community naming with empty list."""
    result = _generate_community_name([])
    assert result == "unnamed"


def test_generate_community_name_no_underscores():
    """Test community naming when no underscores in names."""
    names = ["login", "logout", "refresh"]
    result = _generate_community_name(names)
    # Should pick one of the names
    assert result in ["login", "logout", "refresh"]


def test_generate_community_name_tie_breaking():
    """Test that tie-breaking works (Counter.most_common picks first)."""
    names = ["data_fetch", "auth_login"]
    result = _generate_community_name(names)
    # Should be either "data" or "auth" (both appear once)
    assert result in ["data", "auth", "fetch", "login"]


def test_generate_community_name_complex_names():
    """Test with complex multi-part function names."""
    names = [
        "user_auth_validate_token",
        "user_auth_refresh_session",
        "user_profile_update",
    ]
    result = _generate_community_name(names)
    # "user" and "auth" appear most frequently
    assert result in ["user", "auth"]


@dataclass
class _FakeGraph:
    node_rows: list[dict] = field(default_factory=list)
    edge_rows: list[dict] = field(default_factory=list)
    created_nodes: list = field(default_factory=list)
    created_edges: list = field(default_factory=list)

    async def query(self, cypher: str, params=None):
        q = cypher.strip()
        if "RETURN n.id AS id, n.name AS name, n.kind AS kind" in q:
            return self.node_rows
        if "RETURN a.id AS from_id, b.id AS to_id, r.confidence AS confidence" in q:
            return self.edge_rows
        return []

    async def bulk_create_nodes(self, nodes):
        self.created_nodes.extend(nodes)

    async def bulk_create_edges(self, edges):
        self.created_edges.extend(edges)


@pytest.mark.asyncio
async def test_detect_communities_skips_low_modularity(monkeypatch) -> None:
    class _FakePartition:
        modularity = 0.1
        membership = [0, 0, 0]

    monkeypatch.setattr(
        "loom.analysis.code.communities.leidenalg.find_partition",
        lambda *args, **kwargs: _FakePartition(),
    )

    graph = _FakeGraph(
        node_rows=[
            {"id": "function:x:a", "name": "a", "kind": "function"},
            {"id": "function:x:b", "name": "b", "kind": "function"},
            {"id": "function:x:c", "name": "c", "kind": "function"},
        ],
        edge_rows=[
            {"from_id": "function:x:a", "to_id": "function:x:b", "confidence": 1.0},
            {"from_id": "function:x:b", "to_id": "function:x:c", "confidence": 1.0},
        ],
    )

    result = await detect_communities(graph)

    assert result == {}
    assert graph.created_nodes == []
    assert graph.created_edges == []
