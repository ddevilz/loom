from __future__ import annotations

import pytest

from loom.core.node import Node, NodeKind, NodeSource


def test_make_code_id():
    node_id = Node.make_code_id(NodeKind.FUNCTION, "src/auth.py", "validate_user")
    assert node_id == "function:src/auth.py:validate_user"


def test_code_node_id_validation():
    node = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
    )
    assert node.is_code


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


def test_no_doc_kinds():
    for name in ("DOCUMENT", "SECTION", "CHAPTER", "SUBSECTION", "PARAGRAPH"):
        assert not hasattr(NodeKind, name)
