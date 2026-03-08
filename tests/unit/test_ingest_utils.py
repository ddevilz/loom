from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.ingest.utils import invalidate_edges_for_file


@dataclass
class _FakeGraph:
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.calls.append((cypher.strip(), params))
        return []


@pytest.mark.asyncio
async def test_invalidate_edges_for_file_covers_incoming_and_outgoing_edges() -> None:
    graph = _FakeGraph()

    await invalidate_edges_for_file(graph, path="src/x.py")

    assert len(graph.calls) == 4
    cyphers = [cypher for cypher, _ in graph.calls]
    assert "MATCH (a {path: $path})-[r]->()" in cyphers[0]
    assert "MATCH ()-[r]->(a {path: $path})" in cyphers[1]
    assert "MATCH (a {path: $path})-[r]->()" in cyphers[2]
    assert "MATCH ()-[r]->(a {path: $path})" in cyphers[3]
    assert all(params == {"path": "src/x.py"} for _, params in graph.calls)
