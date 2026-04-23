from __future__ import annotations

from loom.core.graph import LoomGraph


async def build_blast_radius_payload(
    graph: LoomGraph,
    *,
    node_id: str,
    depth: int = 3,
) -> dict[str, object]:
    """Return blast-radius payload for the given node."""
    nodes = await graph.blast_radius(node_id, depth=depth)
    return {
        "node_id": node_id,
        "depth": depth,
        "count": len(nodes),
        "results": [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "kind": n.kind.value,
                "depth": n.depth or 0,
            }
            for n in nodes
        ],
    }
