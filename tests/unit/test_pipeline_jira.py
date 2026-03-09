from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.core import Edge, Node, NodeKind, NodeSource
from loom.ingest.integrations.jira import JiraConfig
from loom.ingest.pipeline import index_repo


@dataclass
class _FakeGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if (
            cypher.strip()
            == "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"
        ):
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

    async def link(self, code_nodes, doc_nodes, graph):
        self.called = True
        return []


@pytest.mark.asyncio
async def test_index_repo_with_jira_adds_jira_nodes(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("loom.ingest.pipeline._collect_repo_files", lambda root: [])
    monkeypatch.setattr(
        "loom.ingest.pipeline.fetch_jira_nodes",
        lambda cfg: [
            Node(
                id="doc:jira:PROJ-1",
                kind=NodeKind.DOCUMENT,
                source=NodeSource.DOC,
                name="PROJ-1",
                path="jira://PROJ/PROJ-1",
                summary="req",
                metadata={},
            )
        ],
    )
    linker = _FakeSemanticLinker()
    monkeypatch.setattr("loom.ingest.pipeline.SemanticLinker", lambda: linker)
    monkeypatch.setattr(
        "loom.ingest.pipeline._collect_code_nodes_for_linking",
        lambda batch: [
            Node(
                id="function:x:f",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name="f",
                path="x",
                summary="req",
                metadata={},
            )
        ],
    )

    graph = _FakeGraph()
    res = await index_repo(
        str(tmp_path),
        graph,
        jira=JiraConfig(
            base_url="https://jira.example.com",
            email="a@b.com",
            api_token="tok",
            project_key="PROJ",
        ),
    )

    assert any(n.name == "PROJ-1" for n in graph.nodes)
    assert res.node_count >= 1
    assert linker.called is True
