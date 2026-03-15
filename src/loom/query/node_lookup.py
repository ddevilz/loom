from __future__ import annotations

from loom.core.node import NodeKind
from loom.core.protocols import QueryGraph


async def resolve_node_rows(
    graph: QueryGraph,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    if ":" in target:
        return [{"id": target}]

    label_clause = ":Node" if kind is None else f":`{kind.name.title()}`"
    if "." in target:
        rows = await graph.query(
            f"""
            MATCH (n{label_clause})
            WHERE n.name = $target
               OR n.id ENDS WITH $qualified_suffix
            RETURN n.id AS id, n.kind AS kind, n.path AS path
            LIMIT $limit
            """,
            {
                "target": target,
                "qualified_suffix": f":{target}",
                "limit": limit,
            },
        )
        if rows:
            return rows
        return await graph.query(
            f"""
            MATCH (n{label_clause})
            WHERE n.name = $leaf_name
            RETURN n.id AS id, n.kind AS kind, n.path AS path
            LIMIT $limit
            """,
            {"leaf_name": target.rsplit(".", 1)[-1], "limit": limit},
        )

    return await graph.query(
        f"MATCH (n{label_clause} {{name: $name}}) "
        "RETURN n.id AS id, n.kind AS kind, n.path AS path "
        "LIMIT $limit",
        {"name": target, "limit": limit},
    )


async def resolve_node_id(
    graph: QueryGraph,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 10,
) -> str | None:
    if ":" in target:
        return target
    rows = await resolve_node_rows(graph, target=target, kind=kind, limit=limit)
    if len(rows) != 1:
        return None
    node_id = rows[0].get("id")
    return node_id if isinstance(node_id, str) else None
