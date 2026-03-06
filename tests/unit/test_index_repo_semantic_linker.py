from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.ingest.pipeline import index_repo


@dataclass
class _FakeGraph:
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


class _FakeSemanticLinker:
    def __init__(self, *args, **kwargs) -> None:
        self.called = False

    async def link(self, code_nodes: list[Node], doc_nodes: list[Node], graph: _FakeGraph) -> list[Edge]:
        self.called = True
        edge = Edge(from_id=code_nodes[0].id, to_id=doc_nodes[0].id, kind=EdgeType.LOOM_IMPLEMENTS, metadata={})
        await graph.bulk_create_edges([edge])
        return [edge]


@pytest.mark.asyncio
async def test_index_repo_with_docs_invokes_semantic_linker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("loom.ingest.pipeline._collect_repo_files", lambda root: [])
    doc_node = Node(id="doc:x:s1", kind=NodeKind.SECTION, source=NodeSource.DOC, name="Req", path="x", summary="req", metadata={})
    monkeypatch.setattr("loom.ingest.docs.base.walk_docs", lambda p: ([doc_node], []))

    linker = _FakeSemanticLinker()
    monkeypatch.setattr("loom.ingest.pipeline.SemanticLinker", lambda: linker)
    monkeypatch.setattr(
        "loom.ingest.pipeline._collect_code_nodes_for_linking",
        lambda batch: [Node(id="function:x:f", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="f", path="x", summary="req", metadata={})],
    )

    graph = _FakeGraph()
    await index_repo(str(tmp_path), graph, docs_path=str(tmp_path))

    assert linker.called is True
    assert graph.edges
