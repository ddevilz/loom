from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_python import language as python_language

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_for_line_span
from loom.ingest.code.languages._ts_utils import (
    get_name as _get_name,
)
from loom.ingest.code.languages._ts_utils import (
    lines as _lines,
)
from loom.ingest.code.languages._ts_utils import (
    node_text as _node_text,
)
from loom.ingest.code.languages._ts_utils import (
    split_params as _split_params,
)
from loom.ingest.code.languages.constants import (
    DEC_ACTION,
    DEC_API_VIEW,
    DEC_APP_DELETE,
    DEC_APP_GET,
    DEC_APP_PATCH,
    DEC_APP_POST,
    DEC_APP_PUT,
    DEC_APP_ROUTE,
    DEC_CSRF_EXEMPT,
    DEC_LOGIN_REQUIRED,
    DEC_PERMISSION_REQUIRED,
    DEC_REQUIRE_HTTP_METHODS,
    DEC_ROUTER_DELETE,
    DEC_ROUTER_GET,
    DEC_ROUTER_PATCH,
    DEC_ROUTER_POST,
    DEC_ROUTER_PUT,
    DEC_SHARED_TASK,
    DEC_TASK,
    HINT_CELERY_TASK,
    HINT_DJANGO_AUTH,
    HINT_DJANGO_VIEW,
    HINT_DRF_ACTION,
    HINT_DRF_VIEW,
    HINT_FASTAPI_ROUTE,
    HINT_FLASK_ROUTE,
    LANG_PYTHON,
    META_DECORATORS,
    META_FRAMEWORK_HINT,
    TS_PY_ATTRIBUTE,
    TS_PY_CALL,
    TS_PY_CLASS_DEF,
    TS_PY_DECORATED_DEF,
    TS_PY_DECORATOR,
    TS_PY_FUNCTION_DEF,
    TS_PY_IDENTIFIER,
)

_PY_LANGUAGE = Language(python_language())


@dataclass(frozen=True)
class _Context:
    class_stack: tuple[str, ...] = ()
    func_stack: tuple[str, ...] = ()

    def push_class(self, name: str) -> _Context:
        return _Context(
            class_stack=self.class_stack + (name,), func_stack=self.func_stack
        )

    def push_func(self, name: str) -> _Context:
        return _Context(
            class_stack=self.class_stack, func_stack=self.func_stack + (name,)
        )

    def qualname(self, name: str) -> str:
        parts: list[str] = []
        if self.class_stack:
            parts.append(".".join(self.class_stack))
        if self.func_stack:
            parts.append(".".join(self.func_stack))
        parts.append(name)
        return ".".join(parts)

    def parent_id(self, path: str) -> str | None:
        if self.func_stack:
            if self.class_stack:
                return Node.make_code_id(
                    NodeKind.METHOD,
                    path,
                    ".".join((*self.class_stack, *self.func_stack)),
                )
            return Node.make_code_id(NodeKind.FUNCTION, path, ".".join(self.func_stack))
        if self.class_stack:
            return Node.make_code_id(NodeKind.CLASS, path, ".".join(self.class_stack))
        return None


def _is_test_path(path: str) -> bool:
    p = Path(path)
    if p.name.startswith("test_") or p.name.endswith("_test.py"):
        return True
    parts = {part.lower() for part in p.parts}
    return "tests" in parts or "test" in parts


def _is_async_function(src: bytes, n: TSNode) -> bool:
    """Check if a function is async."""
    # Check for 'async' keyword before 'def'
    for child in n.children:
        if child.type == "async":
            return True
    return False


def _function_metadata(src: bytes, n: TSNode, *, name: str) -> dict[str, Any]:
    params_node = n.child_by_field_name("parameters")
    return_node = n.child_by_field_name("return_type")
    params = (
        _split_params(_node_text(src, params_node)) if params_node is not None else []
    )
    return_type = (
        _node_text(src, return_node).strip() if return_node is not None else None
    )
    signature = f"{name}({', '.join(params)})"
    if return_type:
        signature = f"{signature} -> {return_type}"
    return {
        "params": params,
        "return_type": return_type,
        "signature": signature,
    }


# ── framework hint rules ────────────────────────────────────────────
_FRAMEWORK_HINTS: dict[str, str] = {
    DEC_APP_ROUTE: HINT_FLASK_ROUTE,
    DEC_APP_GET: HINT_FASTAPI_ROUTE,
    DEC_APP_POST: HINT_FASTAPI_ROUTE,
    DEC_APP_PUT: HINT_FASTAPI_ROUTE,
    DEC_APP_DELETE: HINT_FASTAPI_ROUTE,
    DEC_APP_PATCH: HINT_FASTAPI_ROUTE,
    DEC_ROUTER_GET: HINT_FASTAPI_ROUTE,
    DEC_ROUTER_POST: HINT_FASTAPI_ROUTE,
    DEC_ROUTER_PUT: HINT_FASTAPI_ROUTE,
    DEC_ROUTER_DELETE: HINT_FASTAPI_ROUTE,
    DEC_ROUTER_PATCH: HINT_FASTAPI_ROUTE,
    DEC_LOGIN_REQUIRED: HINT_DJANGO_AUTH,
    DEC_PERMISSION_REQUIRED: HINT_DJANGO_AUTH,
    DEC_REQUIRE_HTTP_METHODS: HINT_DJANGO_VIEW,
    DEC_CSRF_EXEMPT: HINT_DJANGO_VIEW,
    DEC_API_VIEW: HINT_DRF_VIEW,
    DEC_ACTION: HINT_DRF_ACTION,
    DEC_TASK: HINT_CELERY_TASK,
    DEC_SHARED_TASK: HINT_CELERY_TASK,
}


def _get_decorators(src: bytes, decorated_node: TSNode) -> list[str]:
    """Extract decorator name strings from a decorated_definition node."""
    decorators: list[str] = []
    for child in decorated_node.children:
        if child.type == TS_PY_DECORATOR:
            # decorator children: "@" + expression
            # expression can be: identifier, attribute, call
            for part in child.children:
                if part.type == TS_PY_IDENTIFIER or part.type == TS_PY_ATTRIBUTE:
                    decorators.append(_node_text(src, part))
                elif part.type == TS_PY_CALL:
                    fn = part.child_by_field_name("function")
                    if fn is not None:
                        decorators.append(_node_text(src, fn))
    return decorators


def _detect_framework_hint(decorators: list[str]) -> str | None:
    for dec in decorators:
        # check exact match or dotted match
        if dec in _FRAMEWORK_HINTS:
            return _FRAMEWORK_HINTS[dec]
        # also check suffix (e.g. "blueprint.route" matches "*.route")
        parts = dec.rsplit(".", 1)
        if len(parts) == 2:
            suffix_key = parts[0].rsplit(".", 1)[-1] + "." + parts[1]
            if suffix_key in _FRAMEWORK_HINTS:
                return _FRAMEWORK_HINTS[suffix_key]
    return None


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _Context,
    out: list[Node],
    decorators: list[str] | None = None,
) -> None:
    if n.type == TS_PY_DECORATED_DEF:
        decs = _get_decorators(src, n)
        inner = n.child_by_field_name("definition")
        if inner is not None:
            _extract_from_def(
                path=path, src=src, n=inner, ctx=ctx, out=out, decorators=decs
            )
        return

    if n.type == TS_PY_CLASS_DEF:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        meta: dict[str, Any] = {}
        parent_id = ctx.parent_id(path)
        if decorators:
            meta[META_DECORATORS] = decorators
            hint = _detect_framework_hint(decorators)
            if hint:
                meta[META_FRAMEWORK_HINT] = hint
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
                language=LANG_PYTHON,
                parent_id=parent_id,
                metadata=meta,
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_class(name), out=out)
        return

    if n.type == TS_PY_FUNCTION_DEF:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        kind = NodeKind.METHOD if ctx.class_stack else NodeKind.FUNCTION
        parent_id = ctx.parent_id(path)
        if kind == NodeKind.METHOD or ctx.func_stack:
            symbol = ctx.qualname(name)
        else:
            symbol = name
        meta: dict[str, Any] = {}
        meta.update(_function_metadata(src, n, name=name))
        if decorators:
            meta[META_DECORATORS] = decorators
            hint = _detect_framework_hint(decorators)
            if hint:
                meta[META_FRAMEWORK_HINT] = hint
        if _is_async_function(src, n):
            meta["is_async"] = True
        body = n.child_by_field_name("body")
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
                language=LANG_PYTHON,
                parent_id=parent_id,
                metadata=meta,
            )
        )

        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx.push_func(name), out=out)
        return


# TypedDict / namedtuple / NamedTuple — treated as class-like
_CLASS_FACTORY_NAMES = frozenset({"TypedDict", "namedtuple", "NamedTuple"})


def _try_extract_assignment(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _Context,
    out: list[Node],
) -> bool:
    """Handle `name = lambda ...` and `Name = TypedDict(...)` patterns.

    Returns True if the node was consumed.
    """
    if n.type != "expression_statement":
        return False

    for child in n.children:
        if child.type != "assignment":
            continue

        lhs = child.child_by_field_name("left")
        rhs = child.child_by_field_name("right")
        if lhs is None or rhs is None or lhs.type != TS_PY_IDENTIFIER:
            continue

        name = _node_text(src, lhs)
        start_line, end_line = _lines(n)
        parent_id = ctx.parent_id(path)

        # named lambda: my_func = lambda x: ...
        if rhs.type == "lambda":
            symbol = ctx.qualname(name) if ctx.class_stack else name
            kind = NodeKind.METHOD if ctx.class_stack else NodeKind.FUNCTION
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
                    language=LANG_PYTHON,
                    parent_id=parent_id,
                    metadata={"is_lambda": True},
                )
            )
            return True

        # class factory: MyDict = TypedDict(...)
        if rhs.type == TS_PY_CALL:
            func_node = rhs.child_by_field_name("function")
            if func_node is not None:
                func_name = _node_text(src, func_node)
                if func_name in _CLASS_FACTORY_NAMES:
                    out.append(
                        Node(
                            id=f"{NodeKind.CLASS.value}:{path}:{name}",
                            kind=NodeKind.CLASS,
                            source=NodeSource.CODE,
                            name=name,
                            path=path,
                            content_hash=content_hash_for_line_span(
                                src, start_line, end_line
                            ),
                            start_line=start_line,
                            end_line=end_line,
                            language=LANG_PYTHON,
                            parent_id=parent_id,
                            metadata={"class_factory": func_name},
                        )
                    )
                    return True

    return False


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    # We walk all children and recursively extract definitions.
    for child in n.children:
        if child.type in {TS_PY_FUNCTION_DEF, TS_PY_CLASS_DEF, TS_PY_DECORATED_DEF}:
            _extract_from_def(path=path, src=src, n=child, ctx=ctx, out=out)
        elif _try_extract_assignment(path=path, src=src, n=child, ctx=ctx, out=out):
            pass
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out)


def parse_python(path: str, *, exclude_tests: bool = False) -> list[Node]:
    if exclude_tests and _is_test_path(path):
        return []

    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_PY_LANGUAGE)
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(
        path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out
    )
    return out
