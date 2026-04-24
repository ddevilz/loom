"""Standalone MCP server entry point.

Usable via uvx without the full CLI context:
    uvx loom-tool
    # or as explicit entry point:
    uvx --from loom-tool loom-mcp
"""
from __future__ import annotations


def run_stdio() -> None:
    """Start Loom MCP server in stdio transport mode.

    Reads DB path from LOOM_DB_PATH env var, falls back to ~/.loom/loom.db.
    """
    from loom.core.context import DB, DEFAULT_DB_PATH
    from loom.mcp.server import build_server

    db = DB(path=DEFAULT_DB_PATH)
    server = build_server(db=db)
    server.run()
