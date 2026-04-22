from __future__ import annotations

from pathlib import Path

from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_language_pack import get_language as _get_ts_language

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_for_line_span
from loom.ingest.code.languages._base import _BaseContext
from loom.ingest.code.languages._ts_utils import (
    get_name as _get_name,
)
from loom.ingest.code.languages._ts_utils import (
    lines as _lines,
)
from loom.ingest.code.languages._ts_utils import (
    node_text as _node_text,
)
from loom.ingest.code.languages.constants import (
    LANG_RUST,
    META_IMPL_TYPE,
    TS_RUST_ENUM_ITEM,
    TS_RUST_FUNCTION_ITEM,
    TS_RUST_IMPL_ITEM,
    TS_RUST_STRUCT_ITEM,
    TS_RUST_TRAIT_ITEM,
)

_RUST_LANGUAGE = _get_ts_language("rust")


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
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
        ctx.push_class(name)
        _walk(path=path, src=src, n=n, ctx=ctx, out=out)
        ctx.pop_class()
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


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _BaseContext, out: list[Node]) -> None:
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
        path=path.replace("\\", "/"),
        src=src,
        n=tree.root_node,
        ctx=_BaseContext(),
        out=out,
    )
    return out
