from __future__ import annotations

from typing import Any

from falkordb import FalkorDB

_DB_SINGLETON: FalkorDB | None = None


def get_falkordb_singleton() -> FalkorDB:
    global _DB_SINGLETON
    if _DB_SINGLETON is None:
        _DB_SINGLETON = FalkorDB()
    return _DB_SINGLETON


class FalkorGateway:
    def __init__(self, graph_name: str) -> None:
        self.graph_name = graph_name
        self._connect()

    def _connect(self) -> None:
        self._db = get_falkordb_singleton()
        self._graph = self._db.select_graph(self.graph_name)

    def reconnect(self) -> None:
        self._connect()

    def run(self, cypher: str, params: dict[str, Any] | None = None):
        try:
            return self._graph.query(cypher, params=params)
        except Exception:
            self.reconnect()
            return self._graph.query(cypher, params=params)

    def query_rows(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        res = self.run(cypher, params=params)
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
