from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_ruby import language as ruby_language

from loom.core import Node, NodeKind, NodeSource

from loom.ingest.code.languages.constants import (
    LANG_RUBY,
    TS_RUBY_CLASS,
    TS_RUBY_METHOD,
    TS_RUBY_MODULE,
    TS_RUBY_SINGLETON_METHOD,
)

_RUBY_LANGUAGE = Language(ruby_language())


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
    # Ruby: class, module, method, singleton_method
    if n.type in {TS_RUBY_CLASS, TS_RUBY_MODULE}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        kind = NodeKind.MODULE if n.type == TS_RUBY_MODULE else NodeKind.CLASS

        out.append(
            Node(
                id=f"{kind.value}:{path}:{name}:{start_line}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                start_line=start_line,
                end_line=end_line,
                language=LANG_RUBY,
                metadata={},
            )
        )

        # Walk body for nested definitions
        _walk(path=path, src=src, n=n, ctx=ctx.push_class(name), out=out)
        return

    if n.type in {TS_RUBY_METHOD, TS_RUBY_SINGLETON_METHOD}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        
        # Methods inside classes are METHOD, top-level are FUNCTION
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
                language=LANG_RUBY,
                metadata={},
            )
        )
        return


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    for child in n.children:
        if child.type in {TS_RUBY_CLASS, TS_RUBY_MODULE, TS_RUBY_METHOD, TS_RUBY_SINGLETON_METHOD}:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_ruby(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser()
    parser.language = _RUBY_LANGUAGE
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
