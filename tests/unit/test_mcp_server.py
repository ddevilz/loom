from __future__ import annotations

<<<<<<< HEAD
from pathlib import Path

import pytest

from loom.core import LoomGraph
from loom.mcp.server import build_server


def test_build_server_returns_instance_when_fastmcp_available(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")
    try:
        server = build_server(graph=g)
=======
from typing import Any

from loom.core import NodeKind
from loom.mcp.server import _row_to_ast_drift, build_server
from loom.query.traceability import _row_to_code_node, _row_to_doc_node


def test_build_server_returns_instance_when_fastmcp_available() -> None:
    class _StubGraph:
        pass

    try:
        server = build_server("loom", graph=_StubGraph())
>>>>>>> main
    except RuntimeError:
        pytest.skip("fastmcp not installed")
    assert server is not None


<<<<<<< HEAD
def test_build_server_uses_db_path_when_no_graph(tmp_path: Path) -> None:
    db = tmp_path / "loom.db"
    try:
        server = build_server(db_path=db)
    except RuntimeError:
        pytest.skip("fastmcp not installed")
    assert server is not None


@pytest.mark.asyncio
async def test_build_server_registers_all_tools(tmp_path: Path) -> None:
    """All 10 tools should be registered."""
    expected = {
        "search_code",
        "get_node",
        "get_callers",
        "get_callees",
        "get_blast_radius",
        "get_neighbors",
        "get_community",
        "shortest_path",
        "graph_stats",
        "god_nodes",
    }
    g = LoomGraph(db_path=tmp_path / "loom.db")
    try:
        server = build_server(graph=g)
    except RuntimeError:
        pytest.skip("fastmcp not installed")

    # FastMCP.list_tools is async
    tool_list = await server.list_tools()
    tools = {t.name for t in tool_list}
    assert tools == expected
=======
def test_row_to_ast_drift_prefers_structured_reasons() -> None:
    report = _row_to_ast_drift(
        {
            "node_id": "function:x:f",
            "reasons": ["signature_changed: a -> b", "added_parameters: ['x']"],
            "link_reason": "ignored fallback",
        }
    )

    assert report == {
        "node_id": "function:x:f",
        "reasons": ["signature_changed: a -> b", "added_parameters: ['x']"],
    }


def test_row_to_ast_drift_falls_back_to_link_reason() -> None:
    report = _row_to_ast_drift(
        {
            "node_id": "function:x:f",
            "link_reason": "signature_changed: a -> b; return_type_changed: int -> str",
        }
    )

    assert report == {
        "node_id": "function:x:f",
        "reasons": [
            "signature_changed: a -> b",
            "return_type_changed: int -> str",
        ],
    }


def test_row_to_ast_drift_decodes_reasons_from_json_metadata() -> None:
    report = _row_to_ast_drift(
        {
            "node_id": "function:x:f",
            "metadata": '{"reasons": ["signature_changed: a -> b"]}',
        }
    )

    assert report == {
        "node_id": "function:x:f",
        "reasons": ["signature_changed: a -> b"],
    }


def test_row_to_doc_node_preserves_valid_doc_kind() -> None:
    node = _row_to_doc_node(
        {
            "id": "doc:spec.md:ch1",
            "kind": "chapter",
            "name": "Chapter 1",
            "summary": "intro",
            "path": "spec.md",
            "metadata": {},
        }
    )

    assert node is not None
    assert node.kind == NodeKind.CHAPTER


def test_row_to_doc_node_falls_back_to_section_for_invalid_kind() -> None:
    node = _row_to_doc_node(
        {
            "id": "doc:spec.md:s1",
            "kind": "function",
            "name": "Spec",
            "summary": "details",
            "path": "spec.md",
            "metadata": {},
        }
    )

    assert node is not None
    assert node.kind == NodeKind.SECTION


def test_row_to_doc_node_decodes_json_metadata() -> None:
    node = _row_to_doc_node(
        {
            "id": "doc:spec.md:s1",
            "kind": "section",
            "name": "Spec",
            "summary": "details",
            "path": "spec.md",
            "metadata": '{"sprint": "Sprint 1"}',
        }
    )

    assert node is not None
    assert node.metadata == {"sprint": "Sprint 1"}


def test_row_to_code_node_decodes_json_metadata() -> None:
    node = _row_to_code_node(
        {
            "id": "function:x:f",
            "kind": "function",
            "name": "f",
            "summary": "details",
            "path": "x",
            "metadata": '{"owner": "team-a"}',
        }
    )

    assert node is not None
    assert node.metadata == {"owner": "team-a"}


def test_check_drift_queries_loom_violates_relationship_type(monkeypatch) -> None:
    registered_tools: dict[str, Any] = {}

    class _FakeFastMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            def _register(fn):
                registered_tools[fn.__name__] = fn
                return fn

            return _register

    class _FakeGraph:
        def __init__(self) -> None:
            self.queries: list[tuple[str, dict[str, Any] | None]] = []

        async def query(
            self, cypher: str, params: dict[str, Any] | None = None
        ) -> list[dict[str, Any]]:
            self.queries.append((cypher, params))
            if "LOOM_VIOLATES" in cypher:
                return [
                    {
                        "node_id": "function:x:f",
                        "link_method": "ast_diff",
                        "link_reason": "signature_changed: a -> b",
                        "metadata": '{"reasons": ["signature_changed: a -> b"]}',
                    }
                ]
            return []

    fake_graph = _FakeGraph()
    monkeypatch.setattr("loom.mcp.server.FastMCP", _FakeFastMCP)
    build_server("loom", graph=fake_graph)
    tool = registered_tools["check_drift"]

    import asyncio

    output = asyncio.run(tool(node_id="function:x:f"))

    assert output["ast_drift"] == [
        {"node_id": "function:x:f", "reasons": ["signature_changed: a -> b"]}
    ]
    drift_query = next(
        cypher for cypher, _ in fake_graph.queries if "LOOM_VIOLATES" in cypher
    )
    assert "[r:LOOM_VIOLATES]" in drift_query
    assert "r.kind" not in drift_query
    assert "link_method = 'ast_diff'" not in drift_query, (
        "filter moved to Python, not Cypher"
    )
>>>>>>> main
