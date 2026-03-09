from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode
from tree_sitter_typescript import language_tsx, language_typescript

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_for_line_span
from loom.ingest.code.languages.constants import (
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

_TS_LANGUAGE = Language(language_typescript())
_TSX_LANGUAGE = Language(language_tsx())


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


def _split_params(text: str) -> list[str]:
    raw = text.strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _function_metadata(src: bytes, n: TSNode, *, name: str) -> dict:
    params_node = n.child_by_field_name("parameters")
    return_node = n.child_by_field_name("return_type")
    params = (
        _split_params(_node_text(src, params_node)) if params_node is not None else []
    )
    return_type = (
        _node_text(src, return_node).strip() if return_node is not None else None
    )
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
    ctx: _Context,
    out: list[Node],
    language: str,
) -> None:
    # Handle export statements
    if n.type == TS_JS_EXPORT_STATEMENT:
        # Process the exported declaration
        declaration = n.child_by_field_name("declaration")
        if declaration:
            # Try normal definition extraction first
            _extract_from_def(
                path=path, src=src, n=declaration, ctx=ctx, out=out, language=language
            )
            # Also try const function pattern (export const x = () => {})
            _try_extract_const_function(
                path=path, src=src, n=declaration, ctx=ctx, out=out, language=language
            )
        return

    # TypeScript/JavaScript: class_declaration, function_declaration, method_definition
    if n.type == TS_JS_CLASS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)

        # Extract decorators
        metadata = {}
        decorators = _extract_decorators(src, n)
        if decorators:
            metadata["decorators"] = decorators

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
                language=language,
                metadata=metadata,
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx.push_class(name),
                out=out,
                language=language,
            )
        return

    if n.type in {TS_JS_FUNCTION_DECL, TS_JS_FUNCTION, TS_JS_ARROW_FUNCTION}:
        name = _get_name(src, n)
        if not name:
            # arrow functions might not have names
            return

        start_line, end_line = _lines(n)
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
                language=language,
                metadata=metadata,
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx.push_func(name),
                out=out,
                language=language,
            )
        return

    if n.type == TS_JS_METHOD_DEF:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        symbol = ctx.qualname(name)
        body = n.child_by_field_name("body")
        metadata = _function_metadata(src, n, name=name)

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
                language=language,
                metadata=metadata,
            )
        )

        if body is not None:
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx.push_func(name),
                out=out,
                language=language,
            )
        return

    if n.type == TS_JS_ENUM_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        out.append(
            Node(
                id=f"{NodeKind.ENUM.value}:{path}:{name}",
                kind=NodeKind.ENUM,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=language,
                metadata={},
            )
        )
        return

    if n.type == TS_JS_INTERFACE_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        out.append(
            Node(
                id=f"{NodeKind.INTERFACE.value}:{path}:{name}",
                kind=NodeKind.INTERFACE,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=language,
                metadata={},
            )
        )
        return

    if n.type == TS_JS_TYPE_ALIAS_DECL:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)
        out.append(
            Node(
                id=f"{NodeKind.TYPE.value}:{path}:{name}",
                kind=NodeKind.TYPE,
                source=NodeSource.CODE,
                name=name,
                path=path,
                content_hash=content_hash_for_line_span(src, start_line, end_line),
                start_line=start_line,
                end_line=end_line,
                language=language,
                metadata={},
            )
        )
        return


def _try_extract_const_function(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _Context,
    out: list[Node],
    language: str,
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
        start_line, end_line = _lines(n)
        metadata: dict = {}

        if value_node.type == TS_JS_ARROW_FUNCTION:
            metadata["is_arrow"] = True
        for vc in value_node.children:
            if vc.type == "async":
                metadata["is_async"] = True
                break
        body = value_node.child_by_field_name("body")

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
                language=language,
                metadata=metadata,
            )
        )

        if body is not None:
            _walk(
                path=path,
                src=src,
                n=body,
                ctx=ctx.push_func(name),
                out=out,
                language=language,
            )
        found = True

    return found


def _walk(
    *, path: str, src: bytes, n: TSNode, ctx: _Context, out: list[Node], language: str
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
                path=path, src=src, n=child, ctx=ctx, out=out, language=language
            )
        elif _try_extract_const_function(
            path=path, src=src, n=child, ctx=ctx, out=out, language=language
        ):
            pass
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out, language=language)


def parse_typescript(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    is_tsx = p.suffix.lower() == ".tsx"
    parser = Parser(_TSX_LANGUAGE if is_tsx else _TS_LANGUAGE)
    tree = parser.parse(src)

    out: list[Node] = []
    lang = LANG_TSX if is_tsx else LANG_TYPESCRIPT
    _walk(
        path=path.replace("\\", "/"),
        src=src,
        n=tree.root_node,
        ctx=_Context(),
        out=out,
        language=lang,
    )
    return out
