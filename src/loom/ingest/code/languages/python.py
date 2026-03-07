from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tree_sitter import Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser
from tree_sitter_python import language as python_language

from loom.core import Node, NodeKind, NodeSource

from loom.core.content_hash import content_hash_for_line_span

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
    TS_PY_ALIASED_IMPORT,
    TS_PY_ATTRIBUTE,
    TS_PY_CALL,
    TS_PY_CLASS_DEF,
    TS_PY_DECORATED_DEF,
    TS_PY_DECORATOR,
    TS_PY_DOTTED_NAME,
    TS_PY_FUNCTION_DEF,
    TS_PY_IDENTIFIER,
    TS_PY_IMPORT_FROM_STATEMENT,
    TS_PY_IMPORT_STATEMENT,
)
from loom.ingest.code.reflection_detector import detect_python_dynamic_call


_PY_LANGUAGE = Language(python_language())


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


def _is_test_path(path: str) -> bool:
    p = Path(path)
    if p.name.startswith("test_") or p.name.endswith("_test.py"):
        return True
    parts = {part.lower() for part in p.parts}
    return "tests" in parts or "test" in parts


def _node_text(src: bytes, n: TSNode) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


def _get_name(src: bytes, n: TSNode) -> str | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(src, name_node)


def _detect_dynamic_metadata(body: TSNode | None) -> dict[str, Any]:
    if body is None:
        return {}

    stack = [body]
    while stack:
        current = stack.pop()
        detected = detect_python_dynamic_call(current)
        if detected is not None:
            return detected
        stack.extend(reversed(current.children))
    return {}


def _lines(n: TSNode) -> tuple[int, int]:
    # tree-sitter rows are 0-indexed; convert to 1-indexed inclusive
    start_line = n.start_point[0] + 1
    end_line = n.end_point[0] + 1
    return start_line, end_line


def _extract_import_info(src: bytes, n: TSNode) -> dict:
    """Extract import statement details."""
    if n.type == TS_PY_IMPORT_STATEMENT:
        # import foo, bar as baz
        modules = []
        for child in n.children:
            if child.type == TS_PY_DOTTED_NAME:
                modules.append(_node_text(src, child))
            elif child.type == TS_PY_ALIASED_IMPORT:
                # Get the actual module name
                name_node = child.child_by_field_name('name')
                if name_node:
                    modules.append(_node_text(src, name_node))
        return {
            'type': 'import',
            'modules': modules,
            'from': None
        }
    elif n.type == TS_PY_IMPORT_FROM_STATEMENT:
        # from foo import bar, baz
        module_node = n.child_by_field_name('module_name')
        from_module = _node_text(src, module_node) if module_node else ''
        
        imported = []
        for child in n.children:
            if child.type == TS_PY_DOTTED_NAME and child != module_node:
                imported.append(_node_text(src, child))
            elif child.type == TS_PY_ALIASED_IMPORT:
                name_node = child.child_by_field_name('name')
                if name_node:
                    imported.append(_node_text(src, name_node))
        
        return {
            'type': 'from_import',
            'from': from_module,
            'imported': imported
        }
    return {}


def _is_async_function(src: bytes, n: TSNode) -> bool:
    """Check if a function is async."""
    # Check for 'async' keyword before 'def'
    for child in n.children:
        if child.type == 'async':
            return True
    return False


def _split_params(text: str) -> list[str]:
    raw = text.strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _function_metadata(src: bytes, n: TSNode, *, name: str) -> dict[str, Any]:
    params_node = n.child_by_field_name("parameters")
    return_node = n.child_by_field_name("return_type")
    params = _split_params(_node_text(src, params_node)) if params_node is not None else []
    return_type = _node_text(src, return_node).strip() if return_node is not None else None
    signature = f"{name}({', '.join(params)})"
    if return_type:
        signature = f"{signature} -> {return_type}"
    return {
        "params": params,
        "return_type": return_type,
        "signature": signature,
        "source_text": _node_text(src, n),
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
                if part.type == TS_PY_IDENTIFIER:
                    decorators.append(_node_text(src, part))
                elif part.type == TS_PY_ATTRIBUTE:
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
    # Handle import statements
    if n.type in {TS_PY_IMPORT_STATEMENT, TS_PY_IMPORT_FROM_STATEMENT}:
        start_line, end_line = _lines(n)
        import_info = _extract_import_info(src, n)
        
        if import_info.get('type') == 'import':
            # import foo, bar
            for module in import_info.get('modules', []):
                import_name = f"import_{module.replace('.', '_')}"
                out.append(
                    Node(
                        id=f"module:{path}:{import_name}",
                        kind=NodeKind.MODULE,
                        source=NodeSource.CODE,
                        name=import_name,
                        path=path,
                        content_hash=content_hash_for_line_span(src, start_line, end_line),
                        start_line=start_line,
                        end_line=end_line,
                        language=LANG_PYTHON,
                        metadata={
                            'is_import': True,
                            'import_module': module,
                            'import_type': 'import'
                        },
                    )
                )
        elif import_info.get('type') == 'from_import':
            # from foo import bar
            from_module = import_info.get('from', '')
            import_name = f"import_{from_module.replace('.', '_')}"
            out.append(
                Node(
                    id=f"module:{path}:{import_name}",
                    kind=NodeKind.MODULE,
                    source=NodeSource.CODE,
                    name=import_name,
                    path=path,
                    content_hash=content_hash_for_line_span(src, start_line, end_line),
                    start_line=start_line,
                    end_line=end_line,
                    language=LANG_PYTHON,
                    metadata={
                        'is_import': True,
                        'import_from': from_module,
                        'imported_names': import_info.get('imported', []),
                        'import_type': 'from_import'
                    },
                )
            )
        return

    if n.type == TS_PY_DECORATED_DEF:
        decs = _get_decorators(src, n)
        inner = n.child_by_field_name("definition")
        if inner is not None:
            _extract_from_def(path=path, src=src, n=inner, ctx=ctx, out=out, decorators=decs)
        return

    if n.type == TS_PY_CLASS_DEF:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        meta: dict[str, Any] = {}
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
        if kind == NodeKind.METHOD:
            symbol = ctx.qualname(name)
        elif ctx.func_stack:
            symbol = ".".join(ctx.func_stack + (name,))
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
            meta['is_async'] = True
        body = n.child_by_field_name("body")
        meta.update(_detect_dynamic_metadata(body))
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
                            content_hash=content_hash_for_line_span(src, start_line, end_line),
                            start_line=start_line,
                            end_line=end_line,
                            language=LANG_PYTHON,
                            metadata={"class_factory": func_name},
                        )
                    )
                    return True

    return False


def _walk(*, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node]) -> None:
    # We walk all children and recursively extract definitions.
    for child in n.children:
        if child.type in {TS_PY_FUNCTION_DEF, TS_PY_CLASS_DEF, TS_PY_DECORATED_DEF, TS_PY_IMPORT_STATEMENT, TS_PY_IMPORT_FROM_STATEMENT}:
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

    parser = Parser()
    parser.language = _PY_LANGUAGE
    tree = parser.parse(src)

    out: list[Node] = []
    _walk(path=path.replace("\\", "/"), src=src, n=tree.root_node, ctx=_Context(), out=out)
    return out
