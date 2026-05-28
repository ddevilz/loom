from __future__ import annotations

from loom.graph.db import DB
from loom.query.traversal import blast_radius as _blast_radius


async def build_blast_radius_payload(
    db: DB,
    *,
    node_id: str,
    depth: int = 3,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    nodes, total = await _blast_radius(db, node_id, depth=depth, limit=limit, offset=offset)
    truncated = total > offset + limit
    next_offset = offset + limit if truncated else None
    return {
        "node_id": node_id,
        "depth": depth,
        "count": len(nodes),
        "total": total,
        "truncated": truncated,
        "depth_reached": depth,
        "next_offset": next_offset,
        "nodes": [
            {
                "id": n.id,
                "name": n.name,
                "path": n.path,
                "kind": n.kind.value,
                "depth": getattr(n, "depth", None) or 0,
                "summary": n.summary,
            }
            for n in nodes
        ],
    }
