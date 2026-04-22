from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import LoomGraph


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_init_idempotent(tmp_path: Path) -> None:
    g = LoomGraph(db_path=tmp_path / "loom.db")

    # First connection initializes schema
    stats1 = await g.stats()
    assert stats1["nodes"] == 0
    assert stats1["edges"] == 0

    # Second call on same instance is a no-op (schema already exists)
    stats2 = await g.stats()
    assert stats2 == stats1

    # New instance on same file — schema already in place, should still work
    g2 = LoomGraph(db_path=tmp_path / "loom.db")
    stats3 = await g2.stats()
    assert stats3["nodes"] == 0
