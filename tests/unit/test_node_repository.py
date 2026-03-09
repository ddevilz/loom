from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loom.core import Node, NodeKind, NodeSource
from loom.core.falkor.repositories import NodeRepository


@dataclass
class _FakeGateway:
    rows: list[dict[str, Any]]
    run_calls: list[tuple[str, dict[str, Any] | None]] | None = None

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ):
        if self.run_calls is not None:
            self.run_calls.append((cypher, params))
        return None

    def reconnect(self) -> None:
        return None

    def query_rows(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ):
        return self.rows


def test_node_repository_get_returns_none_for_missing_props() -> None:
    repo = NodeRepository(_FakeGateway(rows=[{"id": "function:x:f"}]))  # type: ignore[arg-type]

    node = repo.get("function:x:f")

    assert node is None


def test_node_repository_get_returns_none_for_invalid_props() -> None:
    repo = NodeRepository(
        _FakeGateway(rows=[{"props": {"id": "function:x:f", "kind": "not_a_kind"}}])
    )  # type: ignore[arg-type]

    node = repo.get("function:x:f")

    assert node is None


def test_node_repository_upsert_removes_stale_kind_labels() -> None:
    gateway = _FakeGateway(rows=[], run_calls=[])
    repo = NodeRepository(gateway)  # type: ignore[arg-type]

    repo.upsert(
        Node(
            id="function:x:f",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="f",
            path="x",
            metadata={},
        )
    )

    query, _ = gateway.run_calls[0]
    assert "REMOVE n:`Class`" in query
    assert "REMOVE n:`Method`" in query
    assert "SET n:`Function`" in query


def test_node_repository_bulk_upsert_removes_stale_kind_labels() -> None:
    gateway = _FakeGateway(rows=[], run_calls=[])
    repo = NodeRepository(gateway)  # type: ignore[arg-type]

    repo.bulk_upsert(
        [
            Node(
                id="function:x:f",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name="f",
                path="x",
                metadata={},
            )
        ]
    )

    query, _ = gateway.run_calls[0]
    assert "REMOVE node:`Class`" in query
    assert "REMOVE node:`Method`" in query
    assert "SET node:`Function`" in query
