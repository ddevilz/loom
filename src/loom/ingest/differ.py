from __future__ import annotations

from dataclasses import dataclass

from loom.core import Node


@dataclass(frozen=True)
class NodeDiff:
    added: list[Node]
    deleted: list[Node]
    changed: list[tuple[Node, Node]]
    unchanged: list[Node]


def diff_nodes(old: list[Node], new: list[Node]) -> NodeDiff:
    old_by_id = {n.id: n for n in old}
    new_by_id = {n.id: n for n in new}

    added: list[Node] = []
    deleted: list[Node] = []
    changed: list[tuple[Node, Node]] = []
    unchanged: list[Node] = []

    for node_id, o in old_by_id.items():
        n = new_by_id.get(node_id)
        if n is None:
            deleted.append(o)
            continue
        if (
            isinstance(o.content_hash, str)
            and isinstance(n.content_hash, str)
            and o.content_hash == n.content_hash
        ):
            unchanged.append(n)
            continue
        if (
            o.content_hash is None
            and n.content_hash is None
            and o.kind == n.kind
            and o.path == n.path
            and o.start_line == n.start_line
            and o.end_line == n.end_line
        ):
            unchanged.append(n)
            continue
        changed.append((o, n))

    for node_id, n in new_by_id.items():
        if node_id not in old_by_id:
            added.append(n)

    return NodeDiff(added=added, deleted=deleted, changed=changed, unchanged=unchanged)
