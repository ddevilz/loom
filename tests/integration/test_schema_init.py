import socket

import pytest

from loom.core import LoomGraph
from loom.core.falkor.schema import schema_init


def _falkordb_reachable(host: str = "127.0.0.1", port: int = 6379) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


@pytest.mark.integration
def test_schema_init_idempotent():
    if not _falkordb_reachable():
        pytest.skip("FalkorDB not reachable on 127.0.0.1:6379")

    g = LoomGraph(graph_name="loom_pytest_schema")

    # Access internal gateway just for schema initialization verification.
    schema_init(g._gw)
    schema_init(g._gw)

    # A basic query should still work.
    rows = g.query("RETURN 1 AS x")
    assert rows[0]["x"] == 1
