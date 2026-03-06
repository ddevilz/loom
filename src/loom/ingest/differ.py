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
        if o.content_hash is not None and n.content_hash is not None and o.content_hash != n.content_hash:
            changed.append((o, n))
        else:
            unchanged.append(n)

    for node_id, n in new_by_id.items():
        if node_id not in old_by_id:
            added.append(n)

    return NodeDiff(added=added, deleted=deleted, changed=changed, unchanged=unchanged)
