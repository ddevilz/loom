from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_ruby import language as ruby_language

from loom.core import Node, NodeKind, NodeSource

from loom.core.content_hash import content_hash_for_line_span

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


# Rails DSL method names we want to capture as class metadata
_RAILS_DSL_METHODS = frozenset({
    "has_many", "has_one", "belongs_to", "has_and_belongs_to_many",
    "validates", "validates_presence_of", "validates_uniqueness_of",
    "scope", "default_scope",
    "before_action", "after_action", "around_action",
    "before_filter", "after_filter", "skip_before_action",
    "before_save", "after_save", "before_create", "after_create",
    "before_update", "after_update", "before_destroy", "after_destroy",
    "before_validation", "after_validation",
    "attr_accessor", "attr_reader", "attr_writer",
    "delegate", "alias_method",
})


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
        kind = NodeKind.CLASS

        metadata: dict = {}

        # Extract superclass (class Foo < Bar)
        superclass_node = n.child_by_field_name("superclass")
        if superclass_node:
            for sc_child in superclass_node.children:
                if sc_child.type in {"constant", "scope_resolution"}:
                    metadata["extends"] = _node_text(src, sc_child)
                    break

        # Extract Rails DSL calls from the class body
        dsl_calls: list[dict] = []
        body_node = None
        for child in n.children:
            if child.type == "body_statement":
                body_node = child
                break
        if body_node:
            for child in body_node.children:
                if child.type == "call":
                    call_name_node = None
                    for cc in child.children:
                        if cc.type == "identifier":
                            call_name_node = cc
                            break
                    if call_name_node:
                        call_name = _node_text(src, call_name_node)
                        if call_name in _RAILS_DSL_METHODS:
                            # Extract first argument as the target
                            args_node = None
                            for cc in child.children:
                                if cc.type == "argument_list":
                                    args_node = cc
                                    break
                            target = None
                            if args_node and args_node.child_count > 0:
                                first_arg = args_node.children[0]
                                target = _node_text(src, first_arg)
                            dsl_calls.append({"method": call_name, "target": target})

        if dsl_calls:
            metadata["rails_dsl"] = dsl_calls

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
                language=LANG_RUBY,
                metadata=metadata,
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
                id=f"{kind.value}:{path}:{symbol}",
                kind=kind,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
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

    parser = Parser(_RUBY_LANGUAGE)
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
