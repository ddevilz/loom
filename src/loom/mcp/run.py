"""Standalone MCP server entry point.

Usable via uvx without the full CLI context:
    uvx loom-tool
    # or as explicit entry point:
    uvx --from loom-tool loom-mcp
"""

from __future__ import annotations


def run_stdio() -> None:
    """Start Loom MCP server in stdio transport mode.

    Resolves DB from LOOM_DB_PATH env var, then git-root-based project DB,
    then falls back to ~/.loom/loom.db.
    """
    from loom.core.context import DB, resolve_db_path
    from loom.mcp.server import build_server

    db = DB(path=resolve_db_path())
    server = build_server(db=db)
    server.run()
