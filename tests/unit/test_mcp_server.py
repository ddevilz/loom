from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.mcp.server import build_server


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
    """All 15 tools should be registered."""
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
        "start_session",
        "get_delta",
    }
    db = DB(path=tmp_path / "loom.db")
    try:
        server = build_server(db=db)
    except RuntimeError:
        pytest.skip("fastmcp not installed")

    tool_list = await server.list_tools()
    tools = {t.name for t in tool_list}
    assert tools == expected
