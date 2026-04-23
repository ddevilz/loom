from __future__ import annotations

from loom.core.graph import LoomGraph
from loom.core.node import NodeKind


class AmbiguousNodeError(Exception):
    """Raised when a name matches more than one node."""

    def __init__(self, name: str, count: int) -> None:
        super().__init__(f"Ambiguous target: {count} nodes named {name!r}")
        self.count = count


class NodeNotFoundError(Exception):
    """Raised when a name matches no node."""


async def resolve_node_id(
    graph: LoomGraph,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 2,
) -> str | None:
    """Resolve a target name to a single node id.

    Returns None if the target is not found or matches multiple nodes.
    If target contains ':' it is treated as a direct node id.
    """
    if ":" in target:
        return target

    nodes = await graph.get_nodes_by_name(target, limit=limit)
    if kind is not None:
        nodes = [n for n in nodes if n.kind == kind]

    if len(nodes) == 1:
        return nodes[0].id
    return None
