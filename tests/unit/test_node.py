from __future__ import annotations

import pytest

from loom.core.node import Node, NodeKind, NodeSource


<<<<<<< HEAD
def test_make_code_id():
    node_id = Node.make_code_id(NodeKind.FUNCTION, "src/auth.py", "validate_user")
    assert node_id == "function:src/auth.py:validate_user"
=======
def test_nodekind_has_required_members():
    required = {
        "FUNCTION",
        "CLASS",
        "METHOD",
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
>>>>>>> main


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


<<<<<<< HEAD
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
=======
def test_make_code_id():
    code_id = Node.make_code_id(NodeKind.FUNCTION, "src/auth.py", "validate_user")
    assert code_id == "function:src/auth.py:validate_user"

    method_id = Node.make_code_id(NodeKind.METHOD, "src/user.py", "User.save")
    assert method_id == "method:src/user.py:User.save"

    class_id = Node.make_code_id(NodeKind.CLASS, "models/base.py", "BaseModel")
    assert class_id == "class:models/base.py:BaseModel"


def test_make_doc_id():
    doc_id = Node.make_doc_id("spec.pdf", "3.2.4")
    assert doc_id == "doc:spec.pdf:3.2.4"

    chapter_id = Node.make_doc_id("manual.docx", "chapter-1")
    assert chapter_id == "doc:manual.docx:chapter-1"
>>>>>>> main
