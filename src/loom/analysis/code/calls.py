from __future__ import annotations

from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_python import language as python_language

from loom.analysis.code.noise_filter import should_ignore_call
from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind
from loom.ingest.code.languages.constants import (
    TS_PY_ATTRIBUTE,
    TS_PY_CALL,
    TS_PY_FUNCTION_DEF,
    TS_PY_IDENTIFIER,
)

_PY_LANGUAGE = Language(python_language())


def _node_text(src: bytes, n: TSNode) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


def _extract_call_name(src: bytes, func_node: TSNode) -> tuple[str | None, float]:
    """Extract the function name from a call's function node.

    Returns (name, confidence):
    - Direct call foo() -> ("foo", 1.0)
    - Method call obj.foo() -> ("foo", 0.8)
    - Chained call a.b.c() -> ("c", 0.8)
    - Dynamic/computed -> (None, 0.5)
    """
    if func_node.type == TS_PY_IDENTIFIER:
        name = _node_text(src, func_node)
        return name, 1.0

    if func_node.type == TS_PY_ATTRIBUTE:
        attr_node = func_node.child_by_field_name("attribute")
        if attr_node:
            name = _node_text(src, attr_node)
            return name, 0.8
        return None, 0.5

    return None, 0.5


def _find_calls_in_node(src: bytes, n: TSNode, calls: list[tuple[str, float]]) -> None:
    """Recursively find all call nodes and extract their names."""
    if n.type == TS_PY_CALL:
        func_node = n.child_by_field_name("function")
        if func_node:
            name, confidence = _extract_call_name(src, func_node)
            if name and not should_ignore_call(name):
                calls.append((name, confidence))

    for child in n.children:
        _find_calls_in_node(src, child, calls)


def _find_function_body(
    src: bytes, subtree: TSNode, func_name: str, start_line: int
) -> TSNode | None:
    """Find the function definition node matching the given name and line."""

    def _search(node: TSNode) -> TSNode | None:
        if node.type == TS_PY_FUNCTION_DEF:
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(src, name_node)
                if name == func_name and node.start_point[0] + 1 == start_line:
                    body = node.child_by_field_name("body")
                    return body if body else node

        for child in node.children:
            result = _search(child)
            if result:
                return result
        return None

    return _search(subtree)


def trace_calls(
    function_node: Node,
    subtree: TSNode,
    all_symbols: dict[str, list[Node]],
    *,
    src: bytes | None = None,
) -> list[Edge]:
    """Extract CALLS edges from a function's body.

    Args:
        function_node: The Node representing the function being analyzed
        subtree: The tree-sitter root node (or function body node)
        all_symbols: Dict mapping symbol names to candidate Nodes for resolution
        src: Source bytes (will be read from function_node.path if not provided)

    Returns:
        List of Edge objects with kind=CALLS, including confidence scores
    """
    if src is None:
        src = Path(function_node.path).read_bytes()

    calls: list[tuple[str, float]] = []
    _find_calls_in_node(src, subtree, calls)

    edges: list[Edge] = []
    for callee_name, confidence in calls:
        candidates = all_symbols.get(callee_name, [])
        callee_node: Node | None = None
        if len(candidates) == 1:
            callee_node = candidates[0]
        elif len(candidates) > 1:
            # Heuristic: prefer same file, then prefer function over method
            same_file = [c for c in candidates if c.path == function_node.path]
            pool = same_file or candidates
            funcs = [c for c in pool if c.kind == NodeKind.FUNCTION]
            if len(funcs) == 1:
                callee_node = funcs[0]
            elif len(pool) == 1:
                callee_node = pool[0]

        metadata: dict[str, Any] = {}
        if callee_node is None:
            metadata["unresolved"] = True
            if len(candidates) > 1:
                metadata["ambiguous"] = True

        edges.append(
            Edge(
                from_id=function_node.id,
                to_id=callee_node.id if callee_node else f"unresolved:{callee_name}",
                kind=EdgeType.CALLS,
                origin=EdgeOrigin.COMPUTED,
                confidence=confidence,
                metadata=metadata,
            )
        )

    return edges


def _build_symbol_map(nodes: list[Node]) -> dict[str, list[Node]]:
    """Build a name → [Node] map for all function/method nodes."""
    symbol_map: dict[str, list[Node]] = {}
    for n in nodes:
        if n.kind in {NodeKind.FUNCTION, NodeKind.METHOD}:
            symbol_map.setdefault(n.name, []).append(n)
    return symbol_map


def trace_calls_for_file(path: str, nodes: list[Node]) -> list[Edge]:
    """Trace all CALLS edges for functions in a file.

    Uses only file-local symbols for resolution.  For better cross-file
    accuracy use trace_calls_for_file_with_global_symbols().
    """
    return trace_calls_for_file_with_global_symbols(path, nodes, global_symbol_map=None)


def trace_calls_for_file_with_global_symbols(
    path: str,
    nodes: list[Node],
    *,
    global_symbol_map: dict[str, list[Node]] | None,
) -> list[Edge]:
    """Trace CALLS edges for functions in a file using a cross-file symbol map.

    Args:
        path: Path to the Python file.
        nodes: Nodes extracted from *this* file.
        global_symbol_map: Pre-built name→[Node] map covering the entire repo.
            When provided, cross-file calls resolve to real node IDs instead of
            becoming ``unresolved:<name>``.  If None, falls back to file-local
            symbols only.

    Returns:
        List of CALLS edges for all functions in the file.
    """
    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_PY_LANGUAGE)
    tree = parser.parse(src)

    if global_symbol_map is not None:
        symbol_map = global_symbol_map
    else:
        symbol_map = _build_symbol_map(nodes)

    all_edges: list[Edge] = []
    for node in nodes:
        if node.kind.value in {"function", "method"}:
            func_body = _find_function_body(
                src, tree.root_node, node.name, node.start_line
            )
            if func_body:
                edges = trace_calls(node, func_body, symbol_map, src=src)
                all_edges.extend(edges)

    return all_edges
