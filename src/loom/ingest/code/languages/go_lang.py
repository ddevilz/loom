from __future__ import annotations

from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_go import language as go_language

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
    LANG_GO,
    META_RECEIVER,
    TS_GO_FUNCTION_DECL,
    TS_GO_INTERFACE_TYPE,
    TS_GO_METHOD_DECL,
    TS_GO_PARAMETER_DECL,
    TS_GO_STRUCT_TYPE,
    TS_GO_TYPE_DECL,
    TS_GO_TYPE_SPEC,
)

_GO_LANGUAGE = Language(go_language())


def _qualname(ctx: _BaseContext, name: str) -> str:
    # Go uses class_stack as type_stack
    if ctx.class_stack:
        return ".".join(ctx.class_stack) + "." + name
    return name


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
) -> None:
    # Go: type_declaration (struct/interface), function_declaration, method_declaration
    if n.type == TS_GO_TYPE_DECL:
        # type_spec inside type_declaration
        for child in n.children:
            if child.type == TS_GO_TYPE_SPEC:
                name = _get_name(src, child)
                if not name:
                    continue

                # Check if it's a struct or interface
                type_node = child.child_by_field_name("type")
                if type_node and type_node.type in {
                    TS_GO_STRUCT_TYPE,
                    TS_GO_INTERFACE_TYPE,
                }:
                    start_line, end_line = _lines(child)
                    kind = (
                        NodeKind.INTERFACE
                        if type_node.type == TS_GO_INTERFACE_TYPE
                        else NodeKind.CLASS
                    )

                    out.append(
                        Node(
                            id=f"{kind.value}:{path}:{name}",
                            kind=kind,
                            source=NodeSource.CODE,
                            name=name,
                            path=path,
                            content_hash=content_hash_for_line_span(
                                src, start_line, end_line
                            ),
                            start_line=start_line,
                            end_line=end_line,
                            language=LANG_GO,
                            metadata={},
                        )
                    )

                    # Walk the type body for nested definitions
                    ctx.push_class(name)
                    _walk(
                        path=path,
                        src=src,
                        n=type_node,
                        ctx=ctx,
                        out=out,
                    )
                    ctx.pop_class()
        return

    if n.type == TS_GO_FUNCTION_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
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
                language=LANG_GO,
                metadata={},
            )
        )
        return

    if n.type == TS_GO_METHOD_DECL:
        name = _get_name(src, n)
        if not name:
            return

        # Extract receiver type
        receiver = n.child_by_field_name("receiver")
        receiver_type = None
        if receiver:
            # receiver is a parameter_list, extract the type
            for child in receiver.children:
                if child.type == TS_GO_PARAMETER_DECL:
                    type_node = child.child_by_field_name("type")
                    if type_node:
                        receiver_type = _node_text(src, type_node).strip("*")
                        break

        start_line, end_line = _lines(n)
        symbol = f"{receiver_type}.{name}" if receiver_type else name

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
                language=LANG_GO,
                metadata={META_RECEIVER: receiver_type} if receiver_type else {},
            )
        )
        return


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _BaseContext, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {TS_GO_FUNCTION_DECL, TS_GO_METHOD_DECL, TS_GO_TYPE_DECL}:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_go(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_GO_LANGUAGE)
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
