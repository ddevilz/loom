import pytest

from loom.core.node import Node, NodeKind, NodeSource


def test_nodekind_has_required_members():
    required = {
        "FUNCTION",
        "CLASS",
        "METHOD",
        "MODULE",
        "INTERFACE",
        "ENUM",
        "TYPE",
        "FILE",
        "COMMUNITY",
        "DOCUMENT",
        "SECTION",
        "CHAPTER",
        "SUBSECTION",
        "PARAGRAPH",
    }
    assert required.issubset(set(NodeKind.__members__.keys()))


def test_nodesource_has_required_members():
    assert {"CODE", "DOC"}.issubset(set(NodeSource.__members__.keys()))


def test_code_node_id_convention_and_properties_roundtrip():
    n = Node(
        id="function:src/auth.py:validate_user",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="validate_user",
        path="src/auth.py",
        start_line=10,
        end_line=42,
        language="python",
        is_dead_code=False,
        community_id="c1",
        depth=1,
        parent_id=None,
        metadata={"foo": "bar"},
    )

    assert n.is_code is True
    assert n.is_doc is False

    dumped = n.model_dump()
    n2 = Node.model_validate(dumped)
    assert n2 == n


def test_doc_node_id_convention_and_properties_roundtrip():
    n = Node(
        id="doc:spec.pdf:3.2.4",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="3.2.4",
        path="spec.pdf",
        page_start=3,
        page_end=4,
        depth=2,
        parent_id="doc:spec.pdf:3.2",
        metadata={},
    )

    assert n.is_code is False
    assert n.is_doc is True

    dumped = n.model_dump()
    n2 = Node.model_validate(dumped)
    assert n2 == n


def test_doc_id_must_start_with_doc_prefix():
    with pytest.raises(ValueError):
        Node(
            id="section:spec.pdf:3.2.4",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="3.2.4",
            path="spec.pdf",
            metadata={},
        )


def test_code_id_must_match_kind_prefix():
    with pytest.raises(ValueError):
        Node(
            id="class:src/auth.py:validate_user",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="validate_user",
            path="src/auth.py",
            metadata={},
        )
