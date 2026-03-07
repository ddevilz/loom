from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.core import Edge, Node
from loom.ingest.pipeline import index_repo


@dataclass
class FakeGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if cypher.strip() == "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash":
            return []
        if cypher.strip() == "MATCH (n) RETURN count(n) AS c":
            return [{"c": len(self.nodes)}]
        if cypher.strip() == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": len(self.edges)}]
        return []

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        self.nodes.extend(nodes)

    async def bulk_create_edges(self, edges: list[Edge]) -> None:
        self.edges.extend(edges)


@pytest.mark.asyncio
async def test_index_repo_with_docs_path_upserts_doc_nodes(monkeypatch, tmp_path) -> None:
    # Avoid parsing a real repo; make file list empty.
    monkeypatch.setattr("loom.ingest.pipeline._collect_repo_files", lambda root: [])
    # Mock coupling analysis to avoid git repo requirement
    async def mock_coupling(repo_path, **kwargs):
        return []
    monkeypatch.setattr("loom.ingest.pipeline.analyze_coupling", mock_coupling)

    doc_node = Node(
        id="doc:x:root",
        kind="document",
        source="doc",
        name="x",
        path="x",
        metadata={},
    )

    async_edges: list[Edge] = []

    monkeypatch.setattr(
        "loom.ingest.docs.base.walk_docs",
        lambda p: ([doc_node], async_edges),
    )

    g = FakeGraph()
    res = await index_repo(str(tmp_path), g, docs_path=str(tmp_path))

    # The pipeline may create additional nodes during processing
    # Verify that our doc node is present
    assert any(n.id == "doc:x:root" for n in g.nodes)
    assert res.node_count >= 1
