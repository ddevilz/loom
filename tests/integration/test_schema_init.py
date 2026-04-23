from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import LoomGraph


<<<<<<< HEAD
@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_init_idempotent(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    # First connection initializes schema
    stats1 = await g.stats()
    assert stats1["nodes"] == 0
    assert stats1["edges"] == 0
=======
def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.fixture
async def isolated_graph():
    """Yield a LoomGraph with a unique name and drop it after the test."""
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    name = f"loom_pytest_{uuid.uuid4().hex[:8]}"
    g = LoomGraph(graph_name=name)
    yield g
    try:
        await g.delete()
    except Exception:
        pass


@pytest.mark.integration
async def test_schema_init_idempotent(isolated_graph: LoomGraph):
    g = isolated_graph
>>>>>>> main

    # Second call on same instance is a no-op (schema already exists)
    stats2 = await g.stats()
    assert stats2 == stats1

    # New instance on same file — schema already in place, should still work
    g2 = LoomGraph(db_path=tmp_path / "loom.db")
    stats3 = await g2.stats()
    assert stats3["nodes"] == 0
