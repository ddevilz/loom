from __future__ import annotations

import pytest

from loom.core.node import Node, NodeKind, NodeSource


def test_make_code_id():
    node_id = Node.make_code_id(NodeKind.FUNCTION, "src/auth.py", "validate_user")
    assert node_id == "function:src/auth.py:validate_user"


def test_make_doc_id():
    node_id = Node.make_doc_id("specs/auth.pdf", "chapter_3.2.4")
    assert node_id == "doc:specs/auth.pdf:chapter_3.2.4"


def test_code_node_id_validation():
    node = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
    )
    assert node.is_code
    assert not node.is_doc


def test_doc_node_id_validation():
    node = Node(
        id="doc:a.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="s1",
        path="a.md",
    )
    assert node.is_doc


def test_code_node_rejects_bad_id_prefix():
    with pytest.raises(ValueError):
        Node(
            id="doc:wrong:prefix",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="f",
            path="src/x.py",
        )


def test_file_hash_field():
    node = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
        file_hash="abc123",
    )
    assert node.file_hash == "abc123"


def test_no_ticket_kind():
    assert not hasattr(NodeKind, "TICKET")


def test_no_ticket_source():
    assert not hasattr(NodeSource, "TICKET")
