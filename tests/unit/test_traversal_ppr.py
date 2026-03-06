from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.repositories import TraversalRepository


@dataclass
class _FakeGateway:
    graph_name: str = "test"

    def run(self, cypher: str, params: dict[str, Any] | None = None, *, timeout: int | None = None):
        return None

    def reconnect(self) -> None:
        return None

    def query_rows(self, cypher: str, params: dict[str, Any] | None = None, *, timeout: int | None = None):
        ids = set((params or {}).get("ids") or [])
        rows: list[dict[str, Any]] = []
        if "a" in ids:
            rows.append({"from_id": "a", "to_id": "function:b.py:b", "props": {"id": "function:b.py:b", "kind": "function", "source": "code", "name": "b", "path": "b.py", "metadata": {}}})
            rows.append({"from_id": "a", "to_id": "function:d.py:d", "props": {"id": "function:d.py:d", "kind": "function", "source": "code", "name": "d", "path": "d.py", "metadata": {}}})
        if "function:b.py:b" in ids:
            rows.append({"from_id": "function:b.py:b", "to_id": "function:c.py:c", "props": {"id": "function:c.py:c", "kind": "function", "source": "code", "name": "c", "path": "c.py", "metadata": {}}})
        return rows


def test_traversal_repository_ranks_neighbors_with_ppr() -> None:
    repo = TraversalRepository(_FakeGateway())
    nodes = repo.neighbors("a", depth=2, edge_types=[EdgeType.CALLS])
    ids = [node.id for node in nodes]
    assert "function:b.py:b" in ids[:2]
    assert "function:d.py:d" in ids[:2]
    assert ids.index("function:c.py:c") > ids.index("function:b.py:b")
