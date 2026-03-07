from __future__ import annotations

from loom.mcp.server import build_server


def test_build_server_returns_instance_when_fastmcp_available() -> None:
    try:
        server = build_server("loom")
    except RuntimeError:
        return
    assert server is not None
