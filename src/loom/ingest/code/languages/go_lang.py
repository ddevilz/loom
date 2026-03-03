from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_go import language as go_language

from loom.core import Node, NodeKind, NodeSource

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


@dataclass(frozen=True)
class _Context:
    type_stack: tuple[str, ...] = ()

    def push_type(self, name: str) -> "_Context":
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
                if type_node and type_node.type in {TS_GO_STRUCT_TYPE, TS_GO_INTERFACE_TYPE}:
                    start_line, end_line = _lines(child)
                    kind = NodeKind.INTERFACE if type_node.type == TS_GO_INTERFACE_TYPE else NodeKind.CLASS

                    out.append(
                        Node(
                            id=f"{kind.value}:{path}:{name}",
                            kind=kind,
                            source=NodeSource.CODE,
                            name=name,
                            path=path,
                            start_line=start_line,
                            end_line=end_line,
                            language=LANG_GO,
                            metadata={},
                        )
                    )

                    # Walk the type body for nested definitions
                    _walk(path=path, src=src, n=type_node, ctx=ctx.push_type(name), out=out)
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
                start_line=start_line,
                end_line=end_line,
                language=LANG_GO,
                metadata={META_RECEIVER: receiver_type} if receiver_type else {},
            )
        )
        return


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {TS_GO_FUNCTION_DECL, TS_GO_METHOD_DECL, TS_GO_TYPE_DECL}:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_go(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser()
    parser.language = _GO_LANGUAGE
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
