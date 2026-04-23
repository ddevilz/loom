from __future__ import annotations

from loom.core.context import DB
from loom.query.traversal import blast_radius as _blast_radius


async def build_blast_radius_payload(
    db: DB,
    *,
    node_id: str,
    depth: int = 3,
) -> dict[str, object]:
    nodes = await _blast_radius(db, node_id, depth=depth)
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
