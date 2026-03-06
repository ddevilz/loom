from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource
from loom.linker.name_match import link_by_name


def test_link_by_name_emits_edge_above_threshold() -> None:
    code = Node(
        id="function:x:validate_user",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="validate_user",
        path="x",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:sec1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Input Validation",
        path="spec.md",
        summary="The system must validate user input before processing.",
        metadata={},
    )

    edges = link_by_name([code], [doc], threshold=0.6)
    assert edges
    e = edges[0]
    assert e.from_id == code.id
    assert e.to_id == doc.id
    assert e.link_method == "name_match"


def test_link_by_name_no_edge_when_no_overlap() -> None:
    code = Node(
        id="function:x:hash_pw",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="hash_pw",
        path="x",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:sec1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Input Validation",
        path="spec.md",
        summary="All passwords must be stored securely.",
        metadata={},
    )

    edges = link_by_name([code], [doc], threshold=0.6)
    assert edges == []
