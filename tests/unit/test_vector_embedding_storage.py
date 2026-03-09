from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource
from loom.core.falkor.repositories import NodeRepository


class _FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def run(self, cypher: str, params: dict[str, object] | None = None, timeout=None):
        self.calls.append((cypher, params))

    def query_rows(self, cypher: str, params: dict[str, object] | None = None, timeout=None):
        raise AssertionError("query_rows should not be called in this test")


def test_node_repository_upsert_sets_embedding_via_vecf32() -> None:
    gw = _FakeGateway()
    repo = NodeRepository(gw)  # type: ignore[arg-type]

    node = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="s",
        embedding=[0.1, 0.2, 0.3],
        metadata={},
    )

    repo.upsert(node)

    assert len(gw.calls) == 1
    cypher, params = gw.calls[0]

    assert params is not None
    assert "embedding" in params
    assert params["embedding"] == [0.1, 0.2, 0.3]

    props = params["props"]
    assert isinstance(props, dict)
    assert "embedding" not in props

    # Critical: query must convert to VECTOR via vecf32
    assert "vecf32(" in cypher
    assert "SET n.embedding" in cypher


def test_node_repository_bulk_upsert_sets_embedding_via_vecf32() -> None:
    gw = _FakeGateway()
    repo = NodeRepository(gw)  # type: ignore[arg-type]

    nodes = [
        Node(
            id="function:x:f1",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="f1",
            path="x",
            summary="s",
            embedding=[1.0, 2.0],
            metadata={},
        ),
        Node(
            id="function:x:f2",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="f2",
            path="x",
            summary="s",
            embedding=None,
            metadata={},
        ),
    ]

    repo.bulk_upsert(nodes)

    assert len(gw.calls) == 1
    cypher, params = gw.calls[0]

    assert params is not None
    payload = params["nodes"]
    assert isinstance(payload, list)
    assert payload[0]["embedding"] == [1.0, 2.0]
    assert payload[1]["embedding"] is None
    assert "embedding" not in payload[0]["props"]

    assert "vecf32(" in cypher
    assert "SET node.embedding" in cypher
