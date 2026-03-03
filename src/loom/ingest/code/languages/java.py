from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_java import language as java_language

from loom.core import Node, NodeKind, NodeSource

from loom.ingest.code.languages.constants import (
    LANG_JAVA,
    TS_JAVA_CLASS_DECL,
    TS_JAVA_CTOR_DECL,
    TS_JAVA_ENUM_DECL,
    TS_JAVA_INTERFACE_DECL,
    TS_JAVA_METHOD_DECL,
)

_JAVA_LANGUAGE = Language(java_language())


@dataclass(frozen=True)
class _Context:
    class_stack: tuple[str, ...] = ()

    def push_class(self, name: str) -> "_Context":
        return _Context(class_stack=self.class_stack + (name,))

    def qualname(self, name: str) -> str:
        if self.class_stack:
            return ".".join(self.class_stack) + "." + name
        return name


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
    # Java: class_declaration, interface_declaration, method_declaration, constructor_declaration
    if n.type in {TS_JAVA_CLASS_DECL, TS_JAVA_INTERFACE_DECL, TS_JAVA_ENUM_DECL}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        
        if n.type == TS_JAVA_INTERFACE_DECL:
            kind = NodeKind.INTERFACE
        elif n.type == TS_JAVA_ENUM_DECL:
            kind = NodeKind.ENUM
        else:
            kind = NodeKind.CLASS

        out.append(
            Node(
                id=f"{kind.value}:{path}:{name}:{start_line}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVA,
                metadata={},
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_class(name), out=out)
        return

    if n.type in {TS_JAVA_METHOD_DECL, TS_JAVA_CTOR_DECL}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        
        # Methods inside classes are METHOD, top-level would be FUNCTION (rare in Java)
        kind = NodeKind.METHOD if ctx.class_stack else NodeKind.FUNCTION
        symbol = ctx.qualname(name) if ctx.class_stack else name

        out.append(
            Node(
                id=f"{kind.value}:{path}:{symbol}:{start_line}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                start_line=start_line,
                end_line=end_line,
                language=LANG_JAVA,
                metadata={},
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx, out=out)
        return


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {
            TS_JAVA_CLASS_DECL,
            TS_JAVA_INTERFACE_DECL,
            TS_JAVA_ENUM_DECL,
            TS_JAVA_METHOD_DECL,
            TS_JAVA_CTOR_DECL,
        }:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_java(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser()
    parser.language = _JAVA_LANGUAGE
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
