from __future__ import annotations

from pathlib import Path
from typing import Callable

import tree_sitter_javascript as _ts_javascript
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind, NodeSource
from loom.graph.content_hash import content_hash_for_line_span
from loom.indexer.languages._base import BaseLanguageHandler, _BaseContext
from loom.indexer.languages._ts_utils import (
    get_name as _get_name,
)
from loom.indexer.languages._ts_utils import (
    lines as _lines,
)
from loom.indexer.languages._ts_utils import (
    node_text as _node_text,
)
from loom.indexer.languages.constants import (
    LANG_JAVASCRIPT,
    TS_JS_ARROW_FUNCTION,
    TS_JS_CLASS_DECL,
    TS_JS_FUNCTION,
    TS_JS_FUNCTION_DECL,
    TS_JS_METHOD_DEF,
)

_JS_LANGUAGE = _Language(_ts_javascript.language())

# Type aliases for callables threaded through walk functions
_MakeIdFn = Callable[[NodeKind, str, str], str]
_BuildNodeFn = Callable[..., Node]


def _qualname(ctx: _BaseContext, name: str) -> str:
    parts: list[str] = []
    if ctx.class_stack:
        parts.append(".".join(ctx.class_stack))
    if ctx.fn_stack:
        parts.append(".".join(ctx.fn_stack))
    parts.append(name)
    return ".".join(parts)


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    build_node: _BuildNodeFn,
    make_id: _MakeIdFn,
) -> None:
    if n.type == TS_JS_CLASS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        out.append(
            build_node(n, src, path, kind=NodeKind.CLASS, name=name, symbol=name, metadata={})
        )

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_class(name)
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, build_node=build_node, make_id=make_id)
            ctx.pop_class()
        return

    if n.type in {TS_JS_FUNCTION_DECL, TS_JS_FUNCTION, TS_JS_ARROW_FUNCTION}:
        name = _get_name(src, n)
        if not name:
            return

        kind = NodeKind.FUNCTION
        symbol = name

        out.append(
            build_node(n, src, path, kind=kind, name=name, symbol=symbol, metadata={})
        )

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_fn(name)
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, build_node=build_node, make_id=make_id)
            ctx.pop_fn()
        return

    if n.type == TS_JS_METHOD_DEF:
        name = _get_name(src, n)
        if not name:
            return

        symbol = _qualname(ctx, name)

        out.append(
            build_node(n, src, path, kind=NodeKind.METHOD, name=name, symbol=symbol, metadata={})
        )

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_fn(name)
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, build_node=build_node, make_id=make_id)
            ctx.pop_fn()
        return


def _try_extract_const_function(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    build_node: _BuildNodeFn,
    make_id: _MakeIdFn,
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
        if value_node.type not in {
            TS_JS_ARROW_FUNCTION,
            TS_JS_FUNCTION,
            "function_expression",
        }:
            continue

        name = _node_text(src, name_node)
        metadata: dict = {}

        if value_node.type == TS_JS_ARROW_FUNCTION:
            metadata["is_arrow"] = True
        for vc in value_node.children:
            if vc.type == "async":
                metadata["is_async"] = True
                break

        out.append(
            build_node(n, src, path, kind=NodeKind.FUNCTION, name=name, symbol=name, metadata=metadata)
        )

        body = value_node.child_by_field_name("body")
        if body is not None:
            ctx.push_fn(name)
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, build_node=build_node, make_id=make_id)
            ctx.pop_fn()
        found = True

    return found


def _walk(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    build_node: _BuildNodeFn,
    make_id: _MakeIdFn,
) -> None:
    for child in n.children:
        if child.type in {
            TS_JS_FUNCTION_DECL,
            TS_JS_CLASS_DECL,
            TS_JS_METHOD_DEF,
            TS_JS_FUNCTION,
            TS_JS_ARROW_FUNCTION,
        }:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out, build_node=build_node, make_id=make_id)
        elif _try_extract_const_function(path=path, src=src, n=child, ctx=ctx, out=out, build_node=build_node, make_id=make_id):
            pass
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out, build_node=build_node, make_id=make_id)


class JavaScriptHandler(BaseLanguageHandler):
    """Handler for JavaScript/JSX source files."""

    @property
    def language_name(self) -> str:
        return LANG_JAVASCRIPT

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        from loom.indexer.languages.jsx import extract_jsx_nodes

        is_jsx = rel_path.endswith(".jsx")
        parser = Parser(_JS_LANGUAGE)
        tree = parser.parse(source)

        out: list[Node] = []
        make_id: _MakeIdFn = lambda kind, path, symbol: f"{kind.value}:{self.repo_name}:{path}:{symbol}"
        _walk(
            path=rel_path,
            src=source,
            n=tree.root_node,
            ctx=_BaseContext(),
            out=out,
            build_node=self._build_node,
            make_id=make_id,
        )
        if is_jsx:
            file_node_id = f"file:{rel_path}"
            out.extend(extract_jsx_nodes(rel_path, source, tree.root_node, LANG_JAVASCRIPT, file_node_id))
        return out


def parse_javascript(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    from loom.indexer.languages.jsx import extract_jsx_nodes

    p = Path(path)
    src = p.read_bytes()

    is_jsx = p.suffix.lower() == ".jsx"
    parser = Parser(_JS_LANGUAGE)
    tree = parser.parse(src)

    handler = JavaScriptHandler()
    handler.repo_name = "unknown"

    out: list[Node] = []
    norm_path = path.replace("\\", "/")
    make_id: _MakeIdFn = lambda kind, file_path, symbol: f"{kind.value}:{handler.repo_name}:{file_path}:{symbol}"
    _walk(
        path=norm_path,
        src=src,
        n=tree.root_node,
        ctx=_BaseContext(),
        out=out,
        build_node=handler._build_node,
        make_id=make_id,
    )
    if is_jsx:
        file_node_id = f"file:{norm_path}"
        out.extend(extract_jsx_nodes(norm_path, src, tree.root_node, LANG_JAVASCRIPT, file_node_id))
    return out
