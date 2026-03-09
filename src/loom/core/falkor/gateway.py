from __future__ import annotations

import threading
from typing import Any

from falkordb import FalkorDB

from loom.config import LOOM_DB_HOST, LOOM_DB_PORT

_DB_SINGLETON: FalkorDB | None = None
_DB_SINGLETON_LOCK = threading.Lock()


def get_falkordb_singleton() -> FalkorDB:
    """Get or create FalkorDB singleton with thread-safe double-checked locking.

    This prevents multiple threads from creating duplicate FalkorDB instances,
    which could lead to connection pool exhaustion.
    """
    global _DB_SINGLETON

    # Fast path: return if already initialized
    if _DB_SINGLETON is not None:
        return _DB_SINGLETON

    # Acquire lock for initialization
    with _DB_SINGLETON_LOCK:
        # Double-check after acquiring lock
        if _DB_SINGLETON is None:
            _DB_SINGLETON = FalkorDB(host=LOOM_DB_HOST, port=LOOM_DB_PORT)
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

        Thread-safe: acquires lock before resetting singleton.
        """
        global _DB_SINGLETON
        with _DB_SINGLETON_LOCK:
            _DB_SINGLETON = None
        self._connect()

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ):
        try:
            return self._graph.query(cypher, params=params, timeout=timeout)
        except Exception:
            self.reconnect()
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
                key = (
                    header[i][1]
                    if i < len(header)
                    and isinstance(header[i], (list, tuple))
                    and len(header[i]) > 1
                    else str(i)
                )
                d[key] = v
            out.append(d)
        return out
