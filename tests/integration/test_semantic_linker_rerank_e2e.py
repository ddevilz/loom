from __future__ import annotations

import socket

import pytest

from loom.core import Node, NodeKind, NodeSource, LoomGraph
from loom.core.falkor import queries
from loom.linker.linker import SemanticLinker


class _FakeReranker:
    def rerank(self, code_node: Node, doc_node: Node) -> float:
        if code_node.name == "target" and doc_node.name == "Requirement":
            return 0.93
        return 0.1


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_linker_rerank_persists_best_edge_to_real_graph() -> None:
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    graph = LoomGraph(graph_name="loom_pytest_rerank_e2e")
    await graph.query(queries.CLEAR_GRAPH)

    code = Node(
        id="function:repo/auth.py:target",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="target",
        path="repo/auth.py",
        summary="hash password and validate credentials",
        embedding=[1.0, 0.0],
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:req1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Requirement",
        path="spec.md",
        summary="password hashing requirement",
        embedding=[1.0, 0.0],
        metadata={},
    )

    await graph.bulk_create_nodes([code, doc])

    linker = SemanticLinker(reranker=_FakeReranker(), rerank_threshold=0.5)
    edges = await linker.link([code], [doc], graph)

    assert edges
    rows = await graph.query(
        "MATCH (a {id: $from_id})-[r:LOOM_IMPLEMENTS]->(b {id: $to_id}) RETURN r.confidence AS confidence, r.link_reason AS link_reason",
        {"from_id": code.id, "to_id": doc.id},
    )
    assert rows
    assert float(rows[0]["confidence"]) == pytest.approx(0.93)
    assert "cross_encoder" in str(rows[0]["link_reason"])
