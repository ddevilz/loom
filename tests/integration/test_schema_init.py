from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.context import DB
from loom.query import traversal


@pytest.mark.integration
@pytest.mark.asyncio
async def test_schema_init_idempotent(tmp_path: Path) -> None:
    db = DB(path=tmp_path / "loom.db")

    stats1 = await traversal.stats(db)
    assert stats1["nodes"] == 0
    assert stats1["edges"] == 0

    stats2 = await traversal.stats(db)
    assert stats2 == stats1

    db2 = DB(path=tmp_path / "loom.db")
    stats3 = await traversal.stats(db2)
    assert stats3["nodes"] == 0
