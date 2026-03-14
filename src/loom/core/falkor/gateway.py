from __future__ import annotations

import socket
import threading
from typing import Any
from urllib.parse import urlparse

from falkordb import FalkorDB

from loom.config import LOOM_DB_HOST, LOOM_DB_PORT, LOOM_DB_URL

_DB_SINGLETON: FalkorDB | None = None
_DB_SINGLETON_LOCK = threading.Lock()

try:
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
except Exception:
    RedisConnectionError = ()
    RedisTimeoutError = ()


def _falkordb_connect_kwargs() -> dict[str, Any]:
    parsed = urlparse(LOOM_DB_URL)
    if parsed.hostname is None or parsed.scheme not in ("redis", "rediss", ""):
        return {"host": LOOM_DB_HOST, "port": LOOM_DB_PORT}
    try:
        port = parsed.port
    except ValueError:
        port = None
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

    # Fast path: return if already initialized
    if _DB_SINGLETON is not None:
        return _DB_SINGLETON

    # Acquire lock for initialization
    with _DB_SINGLETON_LOCK:
        # Double-check after acquiring lock
        if _DB_SINGLETON is None:
            _DB_SINGLETON = FalkorDB(**_falkordb_connect_kwargs())
        return _DB_SINGLETON


_CONNECTION_ERROR_TYPES = tuple(
    error_type
    for error_type in (
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        TimeoutError,
        socket.timeout,
        OSError,
        RedisConnectionError,
        RedisTimeoutError,
    )
    if isinstance(error_type, type)
)

_CONNECTION_ERROR_MARKERS = (
    "connection refused",
    "connection reset",
    "connection closed",
    "server closed the connection",
    "socket closed",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection error",
    "network is unreachable",
    "broken pipe",
)


def _is_connection_error(error: Exception) -> bool:
    if isinstance(error, _CONNECTION_ERROR_TYPES):
        return True
    message = str(error).lower()
    return any(marker in message for marker in _CONNECTION_ERROR_MARKERS)


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
        try:
            return self._graph.query(cypher, params=params, timeout=timeout)
        except Exception as e:
            if not _is_connection_error(e):
                raise
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
