from __future__ import annotations

from pathlib import Path

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource


def file_node_id(path: str) -> str:
    return f"{NodeKind.FILE.value}:{path}"


def make_file_node(path: str, *, content_hash: str) -> Node:
    p = Path(path)
    return Node(
        id=file_node_id(path),
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path,
        content_hash=content_hash,
        metadata={},
    )


def build_contains_edges(nodes: list[Node]) -> list[Edge]:
    return [
        Edge(
            from_id=node.parent_id,
            to_id=node.id,
            kind=EdgeType.CONTAINS,
            origin=EdgeOrigin.COMPUTED,
            confidence=1.0,
        )
        for node in nodes
        if isinstance(node.parent_id, str) and node.parent_id
    ]
