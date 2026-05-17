from __future__ import annotations

import json
import subprocess
from subprocess import PIPE


def test_loom_mcp_starts_and_responds() -> None:
    """Spawn loom-mcp, send MCP initialize, assert handshake completes.

    This test catches the exact failure mode users hit when tools don't appear:
    process exits before the MCP handshake.
    """
    init_msg = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0"},
                },
            }
        ).encode()
        + b"\n"
    )

    proc = subprocess.Popen(["loom-mcp"], stdin=PIPE, stdout=PIPE, stderr=PIPE)
    try:
        stdout, _ = proc.communicate(input=init_msg, timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        msg = "loom-mcp did not respond within 10 seconds — server hung on startup"
        raise AssertionError(msg) from None
    finally:
        proc.kill()

    first_line = stdout.split(b"\n")[0]
    assert first_line, "loom-mcp produced no stdout — process likely crashed before MCP handshake"

    response = json.loads(first_line)
    assert "result" in response, f"Expected MCP result, got: {response}"
    assert response["result"]["serverInfo"]["name"] == "loom"
