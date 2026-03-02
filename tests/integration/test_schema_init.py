import socket

import pytest

from loom.core import LoomGraph


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
async def test_schema_init_idempotent():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_schema")

    await g.schema_init()
    await g.schema_init()

    # A basic query should still work.
    rows = await g.query("RETURN 1 AS x")
    assert rows[0]["x"] == 1
