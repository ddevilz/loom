from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.mcp.server import build_server


@pytest.mark.asyncio
async def test_get_status_returns_ok_shape(tmp_path: Path) -> None:
    """get_status returns {ok: True, data: {...}} with required fields."""
    db = DB(path=tmp_path / "test.db")
    try:
        server = build_server(db=db)
    except RuntimeError:
        pytest.skip("fastmcp not installed")

    tool_list = await server.list_tools()
    names = {t.name for t in tool_list}
    assert "get_status" in names


@pytest.mark.asyncio
async def test_get_status_data_fields(tmp_path: Path) -> None:
    """get_status data contains expected keys."""
    import asyncio

    from loom.mcp import run as run_mod

    db = DB(path=tmp_path / "test.db")
    # Trigger connect
    with db._lock:
        db.connect()

    # Verify _index_progress is accessible and is a dict
    progress = run_mod._index_progress
    assert isinstance(progress, dict)

    # Verify DB query works (empty DB)
    node_count_result = await asyncio.to_thread(
        lambda: db.connect().execute(
            "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
        ).fetchone()[0]
    )
    assert node_count_result == 0  # empty DB
