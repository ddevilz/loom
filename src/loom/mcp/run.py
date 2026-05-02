"""Standalone MCP server entry point.

Usable via uvx without the full CLI context:
    uvx loom-tool
    # or as explicit entry point:
    uvx --from loom-tool loom-mcp
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _auto_index_if_empty(db: object) -> None:
    """Spawn background thread to index cwd if DB has no nodes.

    Args:
        db: DB instance already connected to the project database.
    """
    import asyncio
    import threading
    from pathlib import Path

    from loom.core.context import DB as DBType

    db_typed: DBType = db  # type: ignore[assignment]
    with db_typed._lock:
        conn = db_typed.connect()
        count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
        ).fetchone()[0]

    if count > 0:
        return

    repo = Path.cwd()
    logger.info("[auto-index] DB empty — indexing %s in background", repo)

    def _bg() -> None:
        from loom.ingest.pipeline import index_repo

        try:
            asyncio.run(index_repo(repo, db=db_typed))
            logger.info("[auto-index] done")
        except Exception as exc:
            logger.warning("[auto-index] failed: %s", exc)

    threading.Thread(target=_bg, daemon=True, name="loom-auto-index").start()


def run_stdio() -> None:
    """Start Loom MCP server in stdio transport mode.

    Resolves DB from LOOM_DB_PATH env var, then git-root-based project DB,
    then falls back to ~/.loom/loom.db.
    Auto-indexes the current directory in background if DB is empty.
    """
    from loom.core.context import DB, resolve_db_path
    from loom.mcp.server import build_server

    db = DB(path=resolve_db_path())
    _auto_index_if_empty(db)
    server = build_server(db=db)
    server.run()
