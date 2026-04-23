from __future__ import annotations

from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_language_pack import get_language as _get_ts_language

from loom.analysis.code.calls._base import node_text
from loom.analysis.code.noise_filter import should_ignore_call
from loom.core import Edge, EdgeType, Node, NodeKind

_TS_LANGUAGE = _get_ts_language("typescript")
_TSX_LANGUAGE = _get_ts_language("tsx")

_TS_CALL = "call_expression"
_TS_IDENTIFIER = "identifier"
_TS_MEMBER_EXPRESSION = "member_expression"
_TS_FUNCTION_DECL = "function_declaration"
_TS_METHOD_DEF = "method_definition"
_TS_ARROW_FUNCTION = "arrow_function"
_TS_FUNCTION_EXPR = "function"


def _extract_call_name(src: bytes, func_node: TSNode) -> tuple[str | None, float]:
    if func_node.type == _TS_IDENTIFIER:
        return node_text(src, func_node), 1.0

    if func_node.type == _TS_MEMBER_EXPRESSION:
        prop = func_node.child_by_field_name("property")
        if prop is not None and prop.type == _TS_IDENTIFIER:
            return node_text(src, prop), 0.8

    return None, 0.5


def _enclosing_named_function(src: bytes, n: TSNode) -> tuple[str | None, int] | None:
    cur: TSNode | None = n
    while cur is not None:
        if cur.type in {_TS_FUNCTION_DECL, _TS_METHOD_DEF}:
            name_node = cur.child_by_field_name("name")
            if name_node is None:
                return None
            name = node_text(src, name_node)
            start_line = cur.start_point[0] + 1
            return name, start_line

        if cur.type in {_TS_ARROW_FUNCTION, _TS_FUNCTION_EXPR}:
            # Best-effort: if assigned to a variable/property, use that identifier.
            parent = cur.parent
            if parent is not None:
                for field in ("name", "left"):
                    maybe = parent.child_by_field_name(field)
                    if maybe is not None and maybe.type == _TS_IDENTIFIER:
                        start_line = cur.start_point[0] + 1
                        return node_text(src, maybe), start_line

        cur = cur.parent
    return None


def _find_calls(src: bytes, root: TSNode) -> list[tuple[TSNode, str, float]]:
    out: list[tuple[TSNode, str, float]] = []

    def _walk(n: TSNode) -> None:
        if n.type == _TS_CALL:
            fn = n.child_by_field_name("function")
            if fn is not None:
                name, conf = _extract_call_name(src, fn)
                if name and not should_ignore_call(name, language="typescript"):
                    out.append((n, name, conf))
        for ch in n.children:
            _walk(ch)

    _walk(root)
    return out


def trace_calls_for_ts_file(path: str, nodes: list[Node]) -> list[Edge]:
    p = Path(path)
    src = p.read_bytes()

    lang = _TSX_LANGUAGE if p.suffix.lower() == ".tsx" else _TS_LANGUAGE
    parser = Parser(lang)
    tree = parser.parse(src)

    symbol_map: dict[str, list[Node]] = {}
    for n in nodes:
        if n.kind in {NodeKind.FUNCTION, NodeKind.METHOD}:
            symbol_map.setdefault(n.name, []).append(n)

    calls = _find_calls(src, tree.root_node)

    edges: list[Edge] = []
    for call_node, callee_name, confidence in calls:
        enclosing = _enclosing_named_function(src, call_node)
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
                confidence=confidence,
                metadata=metadata,
            )
        )

    return edges
