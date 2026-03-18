from __future__ import annotations

import logging
import threading
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from loom.config import LOOM_DB_HOST, LOOM_DB_PORT, LOOM_DB_URL

logger = logging.getLogger(__name__)

_DB_SINGLETON: FalkorDB | None = None
_DB_SINGLETON_LOCK = threading.Lock()


def _falkordb_connect_kwargs() -> dict[str, Any]:
    parsed = urlparse(LOOM_DB_URL)
    if parsed.hostname is None or parsed.scheme not in ("redis", "rediss", ""):
        return {"host": LOOM_DB_HOST, "port": LOOM_DB_PORT}
    port = parsed.port
    return {
        "host": parsed.hostname,
        "port": LOOM_DB_PORT if port is None else port,
    }


def get_falkordb_singleton() -> FalkorDB:
    """Get or create FalkorDB singleton with thread-safe double-checked locking.

    This prevents multiple threads from creating duplicate FalkorDB instances,
    which could lead to connection pool exhaustion.
    """
    global _DB_SINGLETON
    if _DB_SINGLETON is not None:
        return _DB_SINGLETON

    with _DB_SINGLETON_LOCK:
        if _DB_SINGLETON is None:
            _DB_SINGLETON = FalkorDB(**_falkordb_connect_kwargs())
        return _DB_SINGLETON


class FalkorGateway:
    def __init__(self, graph_name: str) -> None:
        self.graph_name = graph_name
        self._connect()

    def _connect(self) -> None:
        self._db = get_falkordb_singleton()
        self._graph = self._db.select_graph(self.graph_name)

    def reconnect(self) -> None:
        """Reconnect to FalkorDB by resetting singleton and reconnecting.

        Thread-safe: acquires lock before resetting singleton and keeps it during reconnect.
        """
        global _DB_SINGLETON
        with _DB_SINGLETON_LOCK:
            _DB_SINGLETON = None
            self._db = FalkorDB(**_falkordb_connect_kwargs())
            _DB_SINGLETON = self._db
            self._graph = self._db.select_graph(self.graph_name)

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ):
        return self._graph.query(cypher, params=params, timeout=timeout)

    def query_rows(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]:
        res = self.run(cypher, params=params, timeout=timeout)
        header = list(getattr(res, "header", []) or [])

        out: list[dict[str, Any]] = []
        for row in res.result_set:
            d: dict[str, Any] = {}
            for i, v in enumerate(row):
                if (
                    i < len(header)
                    and isinstance(header[i], (list, tuple))
                    and len(header[i]) > 1
                ):
                    key = header[i][1]
                else:
                    logger.warning(
                        "Unexpected FalkorDB header format at column %d: %r — "
                        "using positional key '%d'. Query: %.120s",
                        i,
                        header[i] if i < len(header) else "<missing>",
                        i,
                        cypher,
                    )
                    key = str(i)
                d[key] = v
            out.append(d)
        return out
