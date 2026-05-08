from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.mcp.server import build_server
from loom.store import edges as edge_store
from loom.store import nodes as node_store


def test_build_server_returns_instance_when_fastmcp_available(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")
    try:
        server = build_server(db=db)
    except RuntimeError:
        pytest.skip("fastmcp not installed")
    assert server is not None


def test_build_server_uses_db_path_when_no_db(tmp_path: Path) -> None:
    db_path = tmp_path / "loom.db"
    try:
        server = build_server(db_path=db_path)
    except RuntimeError:
        pytest.skip("fastmcp not installed")
    assert server is not None


@pytest.mark.asyncio
async def test_build_server_registers_all_tools(tmp_path: Path) -> None:
    """All tools should be registered."""
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
        "store_understanding",
        "store_understanding_batch",
        "get_context",
        "get_savings",
        "start_session",
        "get_delta",
        "get_surprising_connections",
        "suggest_questions",
        "get_community_cohesion",
    }
    db = DB(path=tmp_path / "loom.db")
    try:
        server = build_server(db=db)
    except RuntimeError:
        pytest.skip("fastmcp not installed")

    tool_list = await server.list_tools()
    tools = {t.name for t in tool_list}
    assert tools == expected


def test_ok_wraps_data() -> None:
    from loom.mcp.server import _ok
    result = _ok({"foo": "bar"})
    assert result == {"ok": True, "data": {"foo": "bar"}}


def test_ok_wraps_none() -> None:
    from loom.mcp.server import _ok
    result = _ok(None)
    assert result == {"ok": True, "data": None}


def test_ok_wraps_list() -> None:
    from loom.mcp.server import _ok
    result = _ok([1, 2, 3])
    assert result == {"ok": True, "data": [1, 2, 3]}


def test_err_shape_with_suggestion() -> None:
    from loom.mcp.enums import ErrorCode
    from loom.mcp.server import _err
    result = _err(ErrorCode.NODE_NOT_FOUND, "Not found.", "Try search_code.")
    assert result["ok"] is False
    assert result["error_code"] == "NODE_NOT_FOUND"
    assert result["message"] == "Not found."
    assert result["suggestion"] == "Try search_code."


def test_err_shape_without_suggestion() -> None:
    from loom.mcp.enums import ErrorCode
    from loom.mcp.server import _err
    result = _err(ErrorCode.MISSING_ARGS, "Provide args.")
    assert result["ok"] is False
    assert "suggestion" not in result


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="h",
    )


@pytest.fixture
def db(tmp_path: Path) -> DB:
    return DB(path=tmp_path / "test.db")


@pytest.mark.asyncio
async def test_blast_radius_payload_uses_nodes_key(db: DB) -> None:
    """In 0.4.1 the field was renamed from 'results' to 'nodes'."""
    from loom.query.blast_radius import build_blast_radius_payload

    a, b = _fn("a.py", "caller"), _fn("b.py", "target")
    await node_store.bulk_upsert_nodes(db, [a, b])
    await edge_store.bulk_upsert_edges(db, [Edge(from_id=a.id, to_id=b.id, kind=EdgeType.CALLS)])

    payload = await build_blast_radius_payload(db, node_id=b.id, depth=3)
    assert "nodes" in payload
    assert "results" not in payload
    assert payload["nodes"][0]["name"] == "caller"


@pytest.mark.asyncio
async def test_context_packet_summary_source_shape(db: DB) -> None:
    from loom.query.context import get_context_packet

    node = _fn("a.py", "fn")
    await node_store.bulk_upsert_nodes(db, [node])

    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert "summary_source" in packet
    assert packet["summary_source"] in ("AGENT", "AUTO")
