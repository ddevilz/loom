from pathlib import Path

import pytest

from loom.graph.db import DB

_TS = "2024-01-01T00:00:00"


@pytest.mark.asyncio
async def test_store_tags_add_remove_clear(tmp_path: Path):
    from loom.server.tools.graph import _store_tags_impl

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    with db._lock:
        conn = db.connect()
        conn.execute(
            "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
            "VALUES (?, 'function', 'code', 'f', 'x.py', ?)",
            ("function:r:x.py:f", _TS),
        )
        conn.commit()

    # add
    result = await _store_tags_impl(db, "function:r:x.py:f", add=["auth", "wip"])
    assert "auth" in result["agent_tags"]
    assert "wip" in result["agent_tags"]

    # remove one
    result = await _store_tags_impl(db, "function:r:x.py:f", remove=["wip"])
    assert "wip" not in result["agent_tags"]
    assert "auth" in result["agent_tags"]

    # clear all
    result = await _store_tags_impl(db, "function:r:x.py:f", clear=True)
    assert result["agent_tags"] == []


@pytest.mark.asyncio
async def test_store_tags_agent_only_in_agent_tags(tmp_path: Path):
    from loom.server.tools.graph import _store_tags_impl

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    with db._lock:
        conn = db.connect()
        conn.execute(
            "INSERT INTO nodes (id, kind, source, name, path, updated_at) "
            "VALUES (?, 'function', 'code', 'g', 'y.py', ?)",
            ("function:r:y.py:g", _TS),
        )
        conn.commit()

    # Add a system tag manually, then add agent tag
    from loom.graph.repository.tags import TagRepository

    tr = TagRepository(db)
    tr.add_tags("function:r:y.py:g", ["hub"], source="system")

    result = await _store_tags_impl(db, "function:r:y.py:g", add=["wip"])
    # agent_tags only shows agent source
    assert result["agent_tags"] == ["wip"]
    # total_tags includes both
    assert "hub" in result["total_tags"]
    assert "wip" in result["total_tags"]
