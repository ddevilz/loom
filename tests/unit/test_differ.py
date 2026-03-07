from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource
from loom.ingest.differ import diff_nodes


def _n(node_id: str, *, ch: str | None) -> Node:
    # Minimal valid node for diffing
    kind_str = node_id.split(":", 1)[0]
    kind = NodeKind(kind_str)
    return Node(
        id=node_id,
        kind=kind,
        source=NodeSource.CODE,
        name="x",
        path="p",
        content_hash=ch,
        metadata={},
    )


def test_diff_nodes_all_categories() -> None:
    old = [
        _n("function:p:a", ch="1"),
        _n("function:p:b", ch="2"),
        _n("function:p:c", ch="3"),
    ]
    new = [
        _n("function:p:a", ch="1"),  # unchanged
        _n("function:p:b", ch="999"),  # changed
        _n("function:p:d", ch="4"),  # added
    ]

    d = diff_nodes(old, new)

    assert {n.id for n in d.added} == {"function:p:d"}
    assert {n.id for n in d.deleted} == {"function:p:c"}
    assert {(o.id, n.id) for (o, n) in d.changed} == {("function:p:b", "function:p:b")}
    assert {n.id for n in d.unchanged} == {"function:p:a"}


def test_diff_nodes_renamed_function_is_added_plus_deleted() -> None:
    old = [_n("function:p:old_name", ch="x")]
    new = [_n("function:p:new_name", ch="x")]

    d = diff_nodes(old, new)

    assert {n.id for n in d.deleted} == {"function:p:old_name"}
    assert {n.id for n in d.added} == {"function:p:new_name"}


def test_diff_nodes_comment_only_change_treated_unchanged_when_hash_same() -> None:
    old = [_n("function:p:a", ch="same")]
    new = [_n("function:p:a", ch="same")]

    d = diff_nodes(old, new)
    assert not d.changed
    assert {n.id for n in d.unchanged} == {"function:p:a"}
