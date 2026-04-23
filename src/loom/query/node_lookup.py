from __future__ import annotations

from loom.core.context import DB
from loom.core.node import NodeKind
from loom.store.nodes import get_nodes_by_name


class AmbiguousNodeError(Exception):
    def __init__(self, name: str, count: int) -> None:
        super().__init__(f"Ambiguous target: {count} nodes named {name!r}")
        self.count = count


class NodeNotFoundError(Exception):
    pass


async def resolve_node_id(
    db: DB,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 2,
) -> str | None:
    if ":" in target:
        return target
    nodes = await get_nodes_by_name(db, target, limit=limit)
    if kind is not None:
        nodes = [n for n in nodes if n.kind == kind]
    if len(nodes) == 1:
        return nodes[0].id
    return None
