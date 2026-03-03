from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

from loom.analysis.code.calls import trace_calls, trace_calls_for_file
from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource

_PY_LANGUAGE = Language(python_language())


def _parse_and_trace(code: str, func_name: str, all_symbols: dict[str, Node] | None = None) -> list[Edge]:
    """Helper to parse code and trace calls for a specific function."""
    parser = Parser()
    parser.language = _PY_LANGUAGE
    tree = parser.parse(code.encode("utf-8"))
    
    func_node = Node(
        id=f"function:test.py:{func_name}:1",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=func_name,
        path="test.py",
        start_line=1,
        end_line=10,
        language="python",
        metadata={},
    )
    
    if all_symbols is None:
        all_symbols = {}
    
    return trace_calls(func_node, tree.root_node, all_symbols, src=code.encode("utf-8"))


def test_trace_direct_function_call():
    code = """
def caller():
    callee()
"""
    callee_node = Node(
        id="function:test.py:callee:5",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="callee",
        path="test.py",
        start_line=5,
        end_line=6,
        language="python",
        metadata={},
    )
    
    edges = _parse_and_trace(code, "caller", {"callee": callee_node})
    
    assert len(edges) == 1
    assert edges[0].kind == EdgeType.CALLS
    assert edges[0].to_id == callee_node.id
    assert edges[0].confidence == 1.0


def test_trace_method_call():
    code = """
def caller():
    obj.method()
"""
    edges = _parse_and_trace(code, "caller")
    
    assert len(edges) == 1
    assert edges[0].kind == EdgeType.CALLS
    assert "method" in edges[0].to_id
    assert edges[0].confidence == 0.8


def test_trace_chained_method_call():
    code = """
def caller():
    obj.chain.method()
"""
    edges = _parse_and_trace(code, "caller")
    
    assert len(edges) == 1
    assert edges[0].kind == EdgeType.CALLS
    assert "method" in edges[0].to_id
    assert edges[0].confidence == 0.8


def test_trace_filters_builtin_noise():
    code = """
def caller():
    print("hello")
    len([1, 2, 3])
    str(42)
    int("10")
    list(range(5))
"""
    edges = _parse_and_trace(code, "caller")
    
    assert len(edges) == 0


def test_trace_filters_common_methods():
    code = """
def caller():
    items.append(1)
    data.get("key")
    text.split(",")
"""
    edges = _parse_and_trace(code, "caller")
    
    assert len(edges) == 0


def test_trace_nested_calls():
    code = """
def caller():
    outer(inner())
"""
    outer_node = Node(
        id="function:test.py:outer:5",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="outer",
        path="test.py",
        start_line=5,
        end_line=6,
        language="python",
        metadata={},
    )
    inner_node = Node(
        id="function:test.py:inner:8",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="inner",
        path="test.py",
        start_line=8,
        end_line=9,
        language="python",
        metadata={},
    )
    
    edges = _parse_and_trace(code, "caller", {"outer": outer_node, "inner": inner_node})
    
    assert len(edges) == 2
    names = {e.to_id for e in edges}
    assert outer_node.id in names
    assert inner_node.id in names


def test_trace_calls_in_conditionals():
    code = """
def caller():
    if condition:
        foo()
    else:
        bar()
"""
    foo_node = Node(
        id="function:test.py:foo:10",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="test.py",
        start_line=10,
        end_line=11,
        language="python",
        metadata={},
    )
    bar_node = Node(
        id="function:test.py:bar:13",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="bar",
        path="test.py",
        start_line=13,
        end_line=14,
        language="python",
        metadata={},
    )
    
    edges = _parse_and_trace(code, "caller", {"foo": foo_node, "bar": bar_node})
    
    assert len(edges) == 2
    names = {e.to_id for e in edges}
    assert foo_node.id in names
    assert bar_node.id in names


def test_trace_calls_in_loops():
    code = """
def caller():
    for item in items:
        process(item)
"""
    process_node = Node(
        id="function:test.py:process:10",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="process",
        path="test.py",
        start_line=10,
        end_line=11,
        language="python",
        metadata={},
    )
    
    edges = _parse_and_trace(code, "caller", {"process": process_node})
    
    assert len(edges) == 1
    assert edges[0].to_id == process_node.id


def test_trace_unresolved_calls():
    code = """
def caller():
    unknown_function()
"""
    edges = _parse_and_trace(code, "caller", {})
    
    assert len(edges) == 1
    assert edges[0].kind == EdgeType.CALLS
    assert edges[0].to_id == "unresolved:unknown_function"
    assert edges[0].metadata["unresolved"] is True
    assert edges[0].confidence == 1.0


def test_trace_calls_for_file_integration(tmp_path: Path):
    from loom.ingest.code.languages.python import parse_python
    
    code = """
def helper():
    pass

def main():
    helper()
    print("done")
"""
    
    test_file = tmp_path / "test.py"
    test_file.write_text(code, encoding="utf-8")
    
    nodes = parse_python(str(test_file))
    edges = trace_calls_for_file(str(test_file), nodes)
    
    assert len(edges) == 1
    assert edges[0].kind == EdgeType.CALLS
    
    helper_node = next(n for n in nodes if n.name == "helper")
    assert edges[0].to_id == helper_node.id


def test_trace_calls_auth_fixture_integration():
    from loom.ingest.code.languages.python import parse_python
    
    auth_path = Path(__file__).parent.parent / "fixtures" / "sample_repo" / "auth.py"
    if not auth_path.exists():
        return
    
    nodes = parse_python(str(auth_path))
    edges = trace_calls_for_file(str(auth_path), nodes)
    
    assert len(edges) > 0
    assert all(e.kind == EdgeType.CALLS for e in edges)
    
    for edge in edges:
        assert 0.5 <= edge.confidence <= 1.0
