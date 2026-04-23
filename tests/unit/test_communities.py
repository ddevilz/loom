from __future__ import annotations

<<<<<<< HEAD
from pathlib import Path

import pytest

from loom.analysis.communities import compute_communities
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
=======
from dataclasses import dataclass, field

import pytest

from loom.analysis.code.communities import _generate_community_name, detect_communities
>>>>>>> main


def _func(name: str, path: str, line: int) -> Node:
    return Node(
        id=f"function:{path}:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        start_line=line,
        end_line=line + 3,
        language="python",
        metadata={},
    )


@pytest.mark.asyncio
async def test_compute_communities_empty_graph_returns_zero(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    count = await compute_communities(g)
    assert count == 0


<<<<<<< HEAD
@pytest.mark.asyncio
async def test_compute_communities_sets_community_id_on_members(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
=======
def test_generate_community_name_filters_trivial_words():
    names = ["get_user", "get_post", "get_order"]
    result = _generate_community_name(names)
    assert result in ["user", "post", "order"]


def test_generate_community_name_single_word_functions():
    """Test community naming with single-word function names."""
    names = ["login", "logout", "authenticate"]
    result = _generate_community_name(names)
    # Should pick the most common single word
    assert result in ["login", "logout", "authenticate"]
>>>>>>> main

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(4)]
    await g.bulk_upsert_nodes(nodes)

    # Dense ring of CALLS edges
    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[2].id, to_id=nodes[3].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[3].id, to_id=nodes[0].id, kind=EdgeType.CALLS),
    ]
<<<<<<< HEAD
    await g.bulk_upsert_edges(edges)

    count = await compute_communities(g)
    assert count >= 1

    # community_id should be set on all function nodes
    for node in nodes:
        n = await g.get_node(node.id)
        assert n is not None
        assert n.community_id is not None


@pytest.mark.asyncio
async def test_compute_communities_creates_community_kind_nodes(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    names = ["login", "logout", "validate"]
    nodes = [_func(f"auth_{n}", "src/a.py", i * 5) for i, n in enumerate(names)]
    await g.bulk_upsert_nodes(nodes)

    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_upsert_edges(edges)

    await compute_communities(g)

    stats = await g.stats()
    assert stats["nodes_by_kind"].get("community", 0) >= 1


@pytest.mark.asyncio
async def test_compute_communities_idempotent(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    nodes = [_func(f"f{i}", "src/a.py", i * 5) for i in range(3)]
    await g.bulk_upsert_nodes(nodes)
    edges = [
        Edge(from_id=nodes[0].id, to_id=nodes[1].id, kind=EdgeType.CALLS),
        Edge(from_id=nodes[1].id, to_id=nodes[2].id, kind=EdgeType.CALLS),
    ]
    await g.bulk_upsert_edges(edges)

    count1 = await compute_communities(g)
    count2 = await compute_communities(g)

    # Second run should produce same number of communities (old ones cleared first)
    assert count1 == count2

    stats = await g.stats()
    # Should not accumulate duplicate community nodes
    community_count = stats["nodes_by_kind"].get("community", 0)
    assert community_count == count2
=======
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

    class _FakeIgraphModule:
        class Graph:
            def __init__(self, n, edges, directed):
                self._n = n
                self._edges = edges
                self.es = {}

            def vcount(self):
                return self._n

            def ecount(self):
                return len(self._edges)

    class _FakeLeidenalgModule:
        ModularityVertexPartition = object()

        @staticmethod
        def find_partition(*args, **kwargs):
            return _FakePartition()

    monkeypatch.setattr(
        "loom.analysis.code.communities._get_community_modules",
        lambda: (_FakeIgraphModule, _FakeLeidenalgModule),
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
>>>>>>> main
