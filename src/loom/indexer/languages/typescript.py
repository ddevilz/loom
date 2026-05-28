from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import tree_sitter_typescript as _ts_typescript
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _BaseContext
from loom.indexer.languages._ts_utils import (
    get_name as _get_name,
)
from loom.indexer.languages._ts_utils import (
    node_text as _node_text,
)
from loom.indexer.languages._ts_utils import (
    split_params as _split_params,
)
from loom.indexer.languages.constants import (
    LANG_TSX,
    LANG_TYPESCRIPT,
    TS_JS_ARROW_FUNCTION,
    TS_JS_CLASS_DECL,
    TS_JS_DECORATOR,
    TS_JS_ENUM_DECL,
    TS_JS_EXPORT_STATEMENT,
    TS_JS_FUNCTION,
    TS_JS_FUNCTION_DECL,
    TS_JS_INTERFACE_DECL,
    TS_JS_METHOD_DEF,
    TS_JS_TYPE_ALIAS_DECL,
)

_TS_LANGUAGE = _Language(_ts_typescript.language_typescript())
_TSX_LANGUAGE = _Language(_ts_typescript.language_tsx())

# Type alias for the build_node callable matching _build_node signature
_BuildNodeFn = Callable[..., Node]


def _qualname(ctx: _BaseContext, name: str) -> str:
    parts: list[str] = []
    if ctx.class_stack:
        parts.append(".".join(ctx.class_stack))
    if ctx.fn_stack:
        parts.append(".".join(ctx.fn_stack))
    parts.append(name)
    return ".".join(parts)


def _extract_decorators(src: bytes, n: TSNode) -> list[str]:
    """Extract TypeScript decorators like @Component, @Injectable."""
    decorators = []
    for child in n.children:
        if child.type == TS_JS_DECORATOR:
            # Get decorator text (e.g., @Component -> Component)
            dec_text = _node_text(src, child)
            # Remove @ symbol
            if dec_text.startswith("@"):
                dec_text = dec_text[1:]
            # Extract just the decorator name (before parentheses)
            if "(" in dec_text:
                dec_text = dec_text[: dec_text.index("(")]
            decorators.append(dec_text)
    return decorators


def _function_metadata(src: bytes, n: TSNode, *, name: str) -> dict:
    params_node = n.child_by_field_name("parameters")
    return_node = n.child_by_field_name("return_type")
    params = _split_params(_node_text(src, params_node)) if params_node is not None else []
    return_type = _node_text(src, return_node).strip() if return_node is not None else None
    if isinstance(return_type, str) and return_type.startswith(":"):
        return_type = return_type[1:].strip()
    signature = f"{name}({', '.join(params)})"
    if return_type:
        signature = f"{signature} -> {return_type}"
    return {
        "params": params,
        "return_type": return_type,
        "signature": signature,
        "source_text": _node_text(src, n),
    }


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    language: str,
    build_node: _BuildNodeFn,
) -> None:
    # Handle export statements
    if n.type == TS_JS_EXPORT_STATEMENT:
        # Process the exported declaration
        declaration = n.child_by_field_name("declaration")
        if declaration:
            # Try normal definition extraction first
            _extract_from_def(
                path=path,
                src=src,
                n=declaration,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
            # Also try const function pattern (export const x = () => {})
            _try_extract_const_function(
                path=path,
                src=src,
                n=declaration,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
        return

    # TypeScript/JavaScript: class_declaration, function_declaration, method_definition
    if n.type == TS_JS_CLASS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        # Extract decorators
        metadata = {}
        decorators = _extract_decorators(src, n)
        if decorators:
            metadata["decorators"] = decorators

        out.append(
            build_node(n, src, path, kind=NodeKind.CLASS, name=name, symbol=name, metadata=metadata)
        )

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_class(name)
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
            ctx.pop_class()
        return

    if n.type in {TS_JS_FUNCTION_DECL, TS_JS_FUNCTION, TS_JS_ARROW_FUNCTION}:
        name = _get_name(src, n)
        if not name:
            # arrow functions might not have names
            return

        kind = NodeKind.FUNCTION
        symbol = name

        # Extract decorators and check for async
        metadata = {}
        metadata.update(_function_metadata(src, n, name=name))
        decorators = _extract_decorators(src, n)
        if decorators:
            metadata["decorators"] = decorators

        # Check if async function
        for child in n.children:
            if child.type == "async":
                metadata["is_async"] = True
                break

        out.append(build_node(n, src, path, kind=kind, name=name, symbol=symbol, metadata=metadata))

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_fn(name)
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
            ctx.pop_fn()
        return

    if n.type == TS_JS_METHOD_DEF:
        name = _get_name(src, n)
        if not name:
            return

        symbol = _qualname(ctx, name)
        body = n.child_by_field_name("body")
        metadata = _function_metadata(src, n, name=name)

        out.append(
            build_node(
                n, src, path, kind=NodeKind.METHOD, name=name, symbol=symbol, metadata=metadata
            )
        )

        if body is not None:
            ctx.push_fn(name)
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
            ctx.pop_fn()
        return

    if n.type == TS_JS_ENUM_DECL:
        name = _get_name(src, n)
        if not name:
            return

        out.append(
            build_node(n, src, path, kind=NodeKind.ENUM, name=name, symbol=name, metadata={})
        )
        return

    if n.type == TS_JS_INTERFACE_DECL:
        name = _get_name(src, n)
        if not name:
            return

        out.append(
            build_node(n, src, path, kind=NodeKind.INTERFACE, name=name, symbol=name, metadata={})
        )
        return

    if n.type == TS_JS_TYPE_ALIAS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        out.append(
            build_node(n, src, path, kind=NodeKind.TYPE, name=name, symbol=name, metadata={})
        )
        return


def _try_extract_const_function(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    language: str,
    build_node: _BuildNodeFn,
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
        body = value_node.child_by_field_name("body")

        out.append(
            build_node(
                n, src, path, kind=NodeKind.FUNCTION, name=name, symbol=name, metadata=metadata
            )
        )

        if body is not None:
            ctx.push_fn(name)
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
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
    language: str,
    build_node: _BuildNodeFn,
) -> None:
    for child in n.children:
        if child.type in {
            TS_JS_FUNCTION_DECL,
            TS_JS_CLASS_DECL,
            TS_JS_METHOD_DEF,
            TS_JS_FUNCTION,
            TS_JS_ARROW_FUNCTION,
            TS_JS_ENUM_DECL,
            TS_JS_INTERFACE_DECL,
            TS_JS_TYPE_ALIAS_DECL,
            TS_JS_EXPORT_STATEMENT,
        }:
            _extract_from_def(
                path=path,
                src=src,
                n=child,
                ctx=ctx,
                out=out,
                language=language,
                build_node=build_node,
            )
        elif _try_extract_const_function(
            path=path,
            src=src,
            n=child,
            ctx=ctx,
            out=out,
            language=language,
            build_node=build_node,
        ):
            pass
        else:
            if child.child_count:
                _walk(
                    path=path,
                    src=src,
                    n=child,
                    ctx=ctx,
                    out=out,
                    language=language,
                    build_node=build_node,
                )


class TypeScriptHandler(BaseLanguageHandler):
    """Handler for TypeScript/TSX source files."""

    @property
    def language_name(self) -> str:
        return LANG_TYPESCRIPT

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        from loom.indexer.languages.jsx import extract_jsx_nodes

        is_tsx = rel_path.endswith(".tsx")
        parser = Parser(_TSX_LANGUAGE if is_tsx else _TS_LANGUAGE)
        tree = parser.parse(source)

        out: list[Node] = []
        lang = LANG_TSX if is_tsx else LANG_TYPESCRIPT

        # Wrap _build_node to apply the correct language (tsx vs typescript)
        def build_node(ts_node: TSNode, src: bytes, path: str, **kwargs: object) -> Node:
            node = self._build_node(ts_node, src, path, **kwargs)  # type: ignore[arg-type]
            return node.model_copy(update={"language": lang})

        _walk(
            path=rel_path,
            src=source,
            n=tree.root_node,
            ctx=_BaseContext(),
            out=out,
            language=lang,
            build_node=build_node,
        )
        if is_tsx:
            file_node_id = f"file:{rel_path}"
            out.extend(
                extract_jsx_nodes(
                    rel_path, source, tree.root_node, lang, file_node_id, build_node=build_node
                )
            )
        return out


def parse_typescript(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    from loom.indexer.languages._base import _default_repo_name
    from loom.indexer.languages.jsx import extract_jsx_nodes

    p = Path(path)
    src = p.read_bytes()

    is_tsx = p.suffix.lower() == ".tsx"
    parser = Parser(_TSX_LANGUAGE if is_tsx else _TS_LANGUAGE)
    tree = parser.parse(src)

    handler = TypeScriptHandler()
    handler.repo_name = _default_repo_name()

    out: list[Node] = []
    lang = LANG_TSX if is_tsx else LANG_TYPESCRIPT
    norm_path = path.replace("\\", "/")

    # Wrap _build_node to apply the correct language (tsx vs typescript)
    def build_node(ts_node: TSNode, src: bytes, path: str, **kwargs: object) -> Node:
        node = handler._build_node(ts_node, src, path, **kwargs)  # type: ignore[arg-type]
        return node.model_copy(update={"language": lang})

    _walk(
        path=norm_path,
        src=src,
        n=tree.root_node,
        ctx=_BaseContext(),
        out=out,
        language=lang,
        build_node=build_node,
    )
    if is_tsx:
        file_node_id = f"file:{norm_path}"
        out.extend(
            extract_jsx_nodes(
                norm_path, src, tree.root_node, lang, file_node_id, build_node=build_node
            )
        )
    return out
