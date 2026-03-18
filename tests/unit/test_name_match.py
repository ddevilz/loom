from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource
from loom.linker.name_match import link_by_name


def test_tokenize_text_shared_module_is_used() -> None:
    """Both name_match and llm_match must import tokenize_text from _text_utils."""
    import inspect
    import loom.linker.name_match as nm
    import loom.linker.llm_match as lm

    nm_src = inspect.getsource(nm)
    lm_src = inspect.getsource(lm)

    assert "_tokenize_text" not in nm_src, "name_match still defines its own _tokenize_text"
    assert "_tokenize_text" not in lm_src, "llm_match still defines its own _tokenize_text"
    assert "from loom.linker._text_utils import tokenize_text" in nm_src
    assert "from loom.linker._text_utils import tokenize_text" in lm_src


def test_tokenize_text_shared_helper_output() -> None:
    from loom.linker._text_utils import tokenize_text

    tokens = tokenize_text("validateUser input")
    assert "validate" in tokens
    assert "user" in tokens
    assert "input" in tokens


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
