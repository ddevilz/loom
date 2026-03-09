from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_rust import language as rust_language

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_for_line_span
from loom.ingest.code.languages.constants import (
    LANG_RUST,
    META_IMPL_TYPE,
    TS_RUST_ENUM_ITEM,
    TS_RUST_FUNCTION_ITEM,
    TS_RUST_IMPL_ITEM,
    TS_RUST_STRUCT_ITEM,
    TS_RUST_TRAIT_ITEM,
)

_RUST_LANGUAGE = Language(rust_language())


@dataclass(frozen=True)
class _Context:
    type_stack: tuple[str, ...] = ()

    def push_type(self, name: str) -> _Context:
        return _Context(type_stack=self.type_stack + (name,))

    def qualname(self, name: str) -> str:
        if self.type_stack:
            return ".".join(self.type_stack) + "." + name
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
    # Rust: struct_item, enum_item, trait_item, function_item, impl_item
    if n.type in {TS_RUST_STRUCT_ITEM, TS_RUST_ENUM_ITEM, TS_RUST_TRAIT_ITEM}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)

        if n.type == TS_RUST_TRAIT_ITEM:
            kind = NodeKind.INTERFACE
        elif n.type == TS_RUST_ENUM_ITEM:
            kind = NodeKind.ENUM
        else:
            kind = NodeKind.CLASS

        out.append(
            Node(
                id=f"{kind.value}:{path}:{name}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=LANG_RUST,
                metadata={},
            )
        )

        # Walk body for nested items
        _walk(path=path, src=src, n=n, ctx=ctx.push_type(name), out=out)
        return

    if n.type == TS_RUST_FUNCTION_ITEM:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)

        # Top-level functions
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
                language=LANG_RUST,
                metadata={},
            )
        )
        return

    if n.type == TS_RUST_IMPL_ITEM:
        # impl blocks contain methods
        # Extract the type being implemented
        type_node = n.child_by_field_name("type")
        impl_type = None
        if type_node:
            impl_type = _node_text(src, type_node)

        body = n.child_by_field_name("body")
        if body:
            # Walk the impl body for function_item nodes (methods)
            for child in body.children:
                if child.type == TS_RUST_FUNCTION_ITEM:
                    method_name = _get_name(src, child)
                    if not method_name:
                        continue

                    start_line, end_line = _lines(child)
                    symbol = f"{impl_type}.{method_name}" if impl_type else method_name

                    out.append(
                        Node(
                            id=f"{NodeKind.METHOD.value}:{path}:{symbol}",
                            kind=NodeKind.METHOD,
                            source=NodeSource.CODE,
                            name=method_name,
                            path=path,
                            content_hash=content_hash_for_line_span(
                                src, start_line, end_line
                            ),
                            start_line=start_line,
                            end_line=end_line,
                            language=LANG_RUST,
                            metadata={META_IMPL_TYPE: impl_type} if impl_type else {},
                        )
                    )
        return


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {
            TS_RUST_STRUCT_ITEM,
            TS_RUST_ENUM_ITEM,
            TS_RUST_TRAIT_ITEM,
            TS_RUST_FUNCTION_ITEM,
            TS_RUST_IMPL_ITEM,
        }:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_rust(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_RUST_LANGUAGE)
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(
        path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out
    )
    return out
