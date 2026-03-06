from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_java import language as java_language

from loom.analysis.code.noise_filter import should_ignore_call
from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind

_JAVA_LANGUAGE = Language(java_language())

_JAVA_METHOD_INVOCATION = "method_invocation"
_JAVA_OBJECT_CREATION = "object_creation_expression"
_JAVA_METHOD_DECL = "method_declaration"
_JAVA_CTOR_DECL = "constructor_declaration"


def _node_text(src: bytes, n: TSNode) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


def _extract_method_call_name(src: bytes, n: TSNode) -> str | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(src, name_node)


def _extract_constructor_call_name(src: bytes, n: TSNode) -> str | None:
    type_node = n.child_by_field_name("type")
    if type_node is None:
        return None

    # type can be scoped_type_identifier, type_identifier, generic_type, etc.
    # We take the last identifier-looking token.
    text = _node_text(src, type_node)
    text = text.split("<", 1)[0]
    text = text.split(".")[-1]
    text = text.strip()
    return text or None


def _enclosing_named_method(src: bytes, n: TSNode) -> tuple[str | None, int] | None:
    cur: TSNode | None = n
    while cur is not None:
        if cur.type in {_JAVA_METHOD_DECL, _JAVA_CTOR_DECL}:
            name_node = cur.child_by_field_name("name")
            if name_node is None:
                return None
            name = _node_text(src, name_node)
            start_line = cur.start_point[0] + 1
            return name, start_line
        cur = cur.parent
    return None


def _find_calls(src: bytes, root: TSNode) -> list[tuple[TSNode, str, float]]:
    out: list[tuple[TSNode, str, float]] = []

    def _walk(n: TSNode) -> None:
        if n.type == _JAVA_METHOD_INVOCATION:
            name = _extract_method_call_name(src, n)
            if name and not should_ignore_call(name, language="java"):
                out.append((n, name, 1.0))
        elif n.type == _JAVA_OBJECT_CREATION:
            name = _extract_constructor_call_name(src, n)
            if name and not should_ignore_call(name, language="java"):
                out.append((n, name, 0.8))

        for ch in n.children:
            _walk(ch)

    _walk(root)
    return out


def trace_calls_for_java_file(path: str, nodes: list[Node]) -> list[Edge]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser()
    parser.language = _JAVA_LANGUAGE
    tree = parser.parse(src)

    symbol_map: dict[str, list[Node]] = {}
    for n in nodes:
        if n.kind in {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS}:
            symbol_map.setdefault(n.name, []).append(n)

    calls = _find_calls(src, tree.root_node)

    edges: list[Edge] = []
    for call_node, callee_name, confidence in calls:
        enclosing = _enclosing_named_method(src, call_node)
        if enclosing is None:
            continue
        caller_name, caller_start_line = enclosing
        if not caller_name:
            continue

        caller_path = Path(path)
        caller_candidates = [
            c
            for c in symbol_map.get(caller_name, [])
            if Path(c.path) == caller_path and c.start_line == caller_start_line
        ]
        if len(caller_candidates) != 1:
            continue
        caller = caller_candidates[0]

        candidates = symbol_map.get(callee_name, [])
        callee_node: Node | None = None
        if len(candidates) == 1:
            callee_node = candidates[0]

        metadata: dict[str, object] = {}
        if callee_node is None:
            metadata["unresolved"] = True

        edges.append(
            Edge(
                from_id=caller.id,
                to_id=callee_node.id if callee_node else f"unresolved:{callee_name}",
                kind=EdgeType.CALLS,
                origin=EdgeOrigin.COMPUTED,
                confidence=confidence,
                metadata=metadata,
            )
        )

    return edges
