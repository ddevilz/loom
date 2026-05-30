import tree_sitter_python as ts_py
from tree_sitter import Language, Parser

from loom.indexer.calls._base import extract_call_context

PY_LANG = Language(ts_py.language())


def _parse(src: bytes):
    return Parser(PY_LANG).parse(src).root_node


def _find_call(node):
    if node.type == "call":
        return node
    for c in node.children:
        r = _find_call(c)
        if r is not None:
            return r
    return None


def test_extract_call_context_assignment():
    src = b"def f():\n    result = validate(token)\n"
    root = _parse(src)
    call = _find_call(root)
    ctx = extract_call_context(call, src)
    assert ctx is not None
    assert "validate(token)" in ctx


def test_extract_call_context_return():
    src = b"def f():\n    return hash_password(x)\n"
    root = _parse(src)
    call = _find_call(root)
    ctx = extract_call_context(call, src)
    assert ctx is not None
    assert "hash_password" in ctx


def test_extract_call_context_caps_at_200_chars():
    src = (b"def f():\n    result = compute(" + b"x," * 100 + b")\n")
    root = _parse(src)
    call = _find_call(root)
    ctx = extract_call_context(call, src)
    assert ctx is not None
    assert len(ctx) <= 200


def test_edge_metadata_carries_call_context(tmp_path):
    from loom.indexer.calls.python import trace_calls_for_file
    from loom.indexer.languages.python import parse_python

    src = b"def caller():\n    result = callee(x)\n\ndef callee(x):\n    return x\n"
    m_path = tmp_path / "m.py"
    m_path.write_bytes(src)
    nodes = parse_python(str(m_path))
    edges = trace_calls_for_file(str(m_path), nodes)
    calls_edges = [e for e in edges if str(e.kind).endswith("CALLS")]
    assert any(
        e.metadata.get("call_context") and "callee(x)" in e.metadata["call_context"]
        for e in calls_edges
    )
