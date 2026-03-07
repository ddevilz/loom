from __future__ import annotations

import pytest

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.search.searcher import search


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _FakeGraph:
    async def query(self, cypher: str, params=None):
        return [
            {
                "id": "function:x:f",
                "kind": "function",
                "name": "f",
                "summary": "authentication flow",
                "path": "x",
                "metadata": {},
                "embedding": [1.0, 0.0],
            }
        ]

    async def neighbors(self, node_id: str, depth: int = 1, edge_types: list[EdgeType] | None = None, kind=None):
        return [
            Node(
                id="doc:spec:s1",
                kind=NodeKind.SECTION,
                source=NodeSource.DOC,
                name="Auth spec",
                path="spec",
                summary="authentication requirements",
                metadata={},
            )
        ]


@pytest.mark.asyncio
async def test_search_returns_ranked_results_with_graph_expansion() -> None:
    results = await search("authentication", _FakeGraph(), limit=5, embedder=_FakeEmbedder())
    assert results
    assert results[0].node.id == "function:x:f"
    assert any(r.matched_via == "graph" for r in results)
