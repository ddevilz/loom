from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_javascript import language as javascript_language

from loom.core import Node, NodeKind, NodeSource

from loom.core.content_hash import content_hash_for_line_span

from loom.ingest.code.languages.constants import (
    LANG_JAVASCRIPT,
    TS_JS_ARROW_FUNCTION,
    TS_JS_CLASS_DECL,
    TS_JS_FUNCTION,
    TS_JS_FUNCTION_DECL,
    TS_JS_METHOD_DEF,
)

_JS_LANGUAGE = Language(javascript_language())


@dataclass(frozen=True)
class _Context:
    class_stack: tuple[str, ...] = ()
    func_stack: tuple[str, ...] = ()

    def push_class(self, name: str) -> "_Context":
        return _Context(class_stack=self.class_stack + (name,), func_stack=self.func_stack)

    def push_func(self, name: str) -> "_Context":
        return _Context(class_stack=self.class_stack, func_stack=self.func_stack + (name,))

    def qualname(self, name: str) -> str:
        parts: list[str] = []
        if self.class_stack:
            parts.append(".".join(self.class_stack))
        if self.func_stack:
            parts.append(".".join(self.func_stack))
        parts.append(name)
        return ".".join(parts)


def _node_text(src: bytes, n: TSNode) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


def _get_name(src: bytes, n: TSNode) -> str | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(src, name_node)


def _lines(n: TSNode) -> tuple[int, int]:
    start_line = n.start_point[0] + 1
    end_line = n.end_point[0] + 1
    return start_line, end_line


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _Context,
    out: list[Node],
) -> None:
    if n.type == TS_JS_CLASS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        out.append(
            Node(
                id=f"{NodeKind.CLASS.value}:{path}:{name}",
                kind=NodeKind.CLASS,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVASCRIPT,
                metadata={},
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_class(name), out=out)
        return

    if n.type in {TS_JS_FUNCTION_DECL, TS_JS_FUNCTION, TS_JS_ARROW_FUNCTION}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        kind = NodeKind.FUNCTION
        symbol = name

        out.append(
            Node(
                id=f"{kind.value}:{path}:{symbol}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVASCRIPT,
                metadata={},
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_func(name), out=out)
        return

    if n.type == TS_JS_METHOD_DEF:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        symbol = ctx.qualname(name)

        out.append(
            Node(
                id=f"{NodeKind.METHOD.value}:{path}:{symbol}",
                kind=NodeKind.METHOD,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVASCRIPT,
                metadata={},
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_func(name), out=out)
        return


def _try_extract_const_function(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _Context,
    out: list[Node],
) -> bool:
    """Handle `const name = () => {}` and `const name = function() {}`."""
    if n.type != "lexical_declaration":
        return False

    found = False
    for child in n.children:
        if child.type != "variable_declarator":
            continue

        name_node = child.child_by_field_name("name")
        value_node = child.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if name_node.type != "identifier":
            continue
        if value_node.type not in {TS_JS_ARROW_FUNCTION, TS_JS_FUNCTION, "function_expression"}:
            continue

        name = _node_text(src, name_node)
        start_line, end_line = _lines(n)
        metadata: dict = {}

        if value_node.type == TS_JS_ARROW_FUNCTION:
            metadata["is_arrow"] = True
        for vc in value_node.children:
            if vc.type == "async":
                metadata["is_async"] = True
                break

        out.append(
            Node(
                id=f"{NodeKind.FUNCTION.value}:{path}:{name}",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVASCRIPT,
                metadata=metadata,
            )
        )

        body = value_node.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_func(name), out=out)
        found = True

    return found


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {TS_JS_FUNCTION_DECL, TS_JS_CLASS_DECL, TS_JS_METHOD_DEF, TS_JS_FUNCTION, TS_JS_ARROW_FUNCTION}:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        elif _try_extract_const_function(path=path, src=src, n=child, ctx=ctx, out=out):
            pass
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_javascript(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_JS_LANGUAGE)
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
