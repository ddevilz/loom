from __future__ import annotations

from loom.core.node import NodeKind
from loom.core.types import QueryGraph


async def resolve_node_rows(
    graph: QueryGraph,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    if ":" in target:
        return [{"id": target}]

    if kind is not None and not isinstance(kind, NodeKind):
        raise TypeError(f"kind must be a NodeKind enum member, got {kind!r}")
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


class AmbiguousNodeError(Exception):
    """Raised when a name matches more than one node."""

    def __init__(self, name: str, rows: list[dict[str, object]]) -> None:
        super().__init__(f"Ambiguous target: {len(rows)} nodes named {name!r}")
        self.rows = rows


class NodeNotFoundError(Exception):
    """Raised when a name matches no node."""


def resolve_node_id_from_rows(
    name: str,
    rows: list[dict[str, object]],
) -> str:
    """Extract a single node id from resolve_node_rows output.

    Raises:
        NodeNotFoundError: when rows is empty.
        AmbiguousNodeError: when rows has more than one entry.
    """
    if len(rows) == 0:
        raise NodeNotFoundError(f"No node named {name!r}")
    if len(rows) > 1:
        raise AmbiguousNodeError(name, rows)
    raw_id = rows[0].get("id")
    if not isinstance(raw_id, str):
        raise NodeNotFoundError(f"Node {name!r} has no id")
    return raw_id


async def resolve_node_id(
    graph: QueryGraph,
    *,
    target: str,
    kind: NodeKind | None = None,
    limit: int = 10,
) -> str | None:
    """Resolve a target name to a single node id, returning None if not found or ambiguous.

    Callers that need to distinguish "not found" from "ambiguous" should use
    resolve_node_rows + resolve_node_id_from_rows directly.
    """
    if ":" in target:
        return target
    rows = await resolve_node_rows(graph, target=target, kind=kind, limit=limit)
    try:
        return resolve_node_id_from_rows(target, rows)
    except (NodeNotFoundError, AmbiguousNodeError):
        return None
