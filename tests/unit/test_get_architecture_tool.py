from pathlib import Path

import pytest

from loom.graph.db import DB


@pytest.mark.asyncio
async def test_get_architecture_returns_expected_shape(tmp_path: Path):
    from loom.server.tools.analysis import _build_architecture_response

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    result = _build_architecture_response(db)
    assert "layers" in result
    assert "dependencies" in result
    assert "violations" in result
    assert "framework_detected" in result
    assert result["framework_detected"] in (
        "generic",
        "django",
        "spring",
        "go",
        "fastapi",
        "flask",
        "nextjs",
        "laravel",
    )


@pytest.mark.asyncio
async def test_get_architecture_with_layers(tmp_path: Path):
    from loom.server.tools.analysis import _build_architecture_response

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    # Seed a layered node
    with db._lock:
        conn = db.connect()
        conn.execute(
            "INSERT INTO nodes (id, kind, source, name, path, updated_at, layer) "
            "VALUES (?, 'function', 'code', 'f', 'src/api/x.py', '2024-01-01', 'api')",
            ("function:r:src/api/x.py:f",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('framework', 'fastapi')",
        )
        conn.commit()
    result = _build_architecture_response(db)
    assert result["framework_detected"] == "fastapi"
    assert "api" in result["layers"]
    assert result["layers"]["api"]["node_count"] == 1
