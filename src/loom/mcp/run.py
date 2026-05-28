from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Module-level progress dict — written by background index thread, read by get_status()
# GIL protects simple dict reads/writes in CPython; no extra lock needed.
_index_progress: dict = {}


def _auto_index_if_empty(db: object) -> None:
    """Spawn background thread to index cwd if DB has no nodes.

    Uses a **separate** DB connection for indexing so the shared lock on the
    main ``db`` instance is never held during long writes.  SQLite WAL mode
    (enabled in ``connect()``) allows concurrent reads from tool handlers
    while the background thread writes.

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
        count = conn.execute("SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL").fetchone()[0]

    if count > 0:
        return

    repo = Path.cwd()
    db_path = db_typed.path
    logger.info("[auto-index] DB empty — indexing %s in background", repo)

    def _on_progress(phase: str, done: int, total: int) -> None:
        _index_progress.update(
            {"phase": phase, "files_processed": done, "files_total": total, "indexing": True}
        )

    def _bg() -> None:
        from loom.ingest.pipeline import index_repo

        # Separate DB instance → own connection + own lock.
        # Tool calls on the main DB instance won't block.
        bg_db = DBType(path=db_path)
        _index_progress["indexing"] = True
        try:
            asyncio.run(index_repo(repo, db=bg_db, progress_cb=_on_progress))
            logger.info("[auto-index] done")
        except Exception as exc:
            logger.warning("[auto-index] failed: %s", exc)
        finally:
            _index_progress["indexing"] = False

    threading.Thread(target=_bg, daemon=True, name="loom-auto-index").start()


def run_stdio() -> None:
    """Start Loom MCP server in stdio transport mode."""
    from loom.core.context import DB, resolve_db_path
    from loom.mcp.server import build_server

    db = DB(path=resolve_db_path())
    _auto_index_if_empty(db)
    server = build_server(db=db)
    server.run()
