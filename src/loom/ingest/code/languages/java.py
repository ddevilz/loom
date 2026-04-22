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
from loom.ingest.code.languages._ts_utils import (
    split_params as _split_params,
)
from loom.ingest.code.languages.constants import (
    LANG_JAVA,
    TS_JAVA_ANNOTATION,
    TS_JAVA_ANNOTATION_TYPE_DECL,
    TS_JAVA_CLASS_DECL,
    TS_JAVA_CTOR_DECL,
    TS_JAVA_ENUM_DECL,
    TS_JAVA_INTERFACE_DECL,
    TS_JAVA_LAMBDA_EXPRESSION,
    TS_JAVA_MARKER_ANNOTATION,
    TS_JAVA_METHOD_DECL,
    TS_JAVA_METHOD_REFERENCE,
    TS_JAVA_MODIFIERS,
    TS_JAVA_RECORD_DECL,
)

_JAVA_LANGUAGE = _get_ts_language("java")


def _qualname(ctx: _BaseContext, name: str, package: str = "") -> str:
    parts: list[str] = []
    if package:
        parts.append(package)
    if ctx.class_stack:
        parts.append(".".join(ctx.class_stack))
    parts.append(name)
    return ".".join(parts)


def _extract_annotations(src: bytes, n: TSNode) -> list[str]:
    """Extract annotations from a node's modifiers."""
    annotations = []
    # Annotations are children of the modifiers node or direct children
    for child in n.children:
        if child.type == TS_JAVA_MODIFIERS:
            # Look inside modifiers for annotations
            for mod_child in child.children:
                if mod_child.type in {TS_JAVA_ANNOTATION, TS_JAVA_MARKER_ANNOTATION}:
                    name_node = mod_child.child_by_field_name("name")
                    if name_node:
                        ann_text = _node_text(src, name_node)
                        annotations.append(ann_text)
        elif child.type in {TS_JAVA_ANNOTATION, TS_JAVA_MARKER_ANNOTATION}:
            # Direct annotation (less common)
            name_node = child.child_by_field_name("name")
            if name_node:
                ann_text = _node_text(src, name_node)
                annotations.append(ann_text)
    return annotations


def _extract_modifiers(src: bytes, n: TSNode) -> list[str]:
    """Extract modifiers like public, private, static, abstract, etc."""
    modifiers = []
    for child in n.children:
        if child.type == TS_JAVA_MODIFIERS:
            for mod_child in child.children:
                if mod_child.type in {
                    "public",
                    "private",
                    "protected",
                    "static",
                    "final",
                    "abstract",
                    "synchronized",
                    "native",
                    "strictfp",
                    "transient",
                    "volatile",
                }:
                    modifiers.append(mod_child.type)
    return modifiers


def _extract_superclass(src: bytes, n: TSNode) -> str | None:
    """Extract superclass from extends clause."""
    superclass_node = n.child_by_field_name("superclass")
    if superclass_node:
        return _node_text(src, superclass_node)
    return None


def _extract_interfaces(src: bytes, n: TSNode) -> list[str]:
    """Extract implemented/extended interfaces."""
    interfaces = []
    super_interfaces = n.child_by_field_name("interfaces")
    if super_interfaces:
        for child in super_interfaces.children:
            if child.type == "type_identifier":
                interfaces.append(_node_text(src, child))
    return interfaces


def _extract_type_parameters(src: bytes, n: TSNode) -> str | None:
    """Extract generic type parameters like <T>, <K, V>."""
    type_params = n.child_by_field_name("type_parameters")
    if type_params:
        return _node_text(src, type_params)
    return None


def _method_metadata(src: bytes, n: TSNode, *, name: str) -> dict:
    params_node = n.child_by_field_name("parameters")
    return_node = n.child_by_field_name("type")
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
        "source_text": _node_text(src, n),
    }


def _count_lambdas_and_refs(src: bytes, n: TSNode) -> dict[str, int]:
    """Count lambda expressions and method references in a node tree."""
    counts = {"lambda_count": 0, "method_ref_count": 0}
    stack = [n]
    while stack:
        node = stack.pop()
        if node.type == TS_JAVA_LAMBDA_EXPRESSION:
            counts["lambda_count"] += 1
        elif node.type == TS_JAVA_METHOD_REFERENCE:
            counts["method_ref_count"] += 1
        stack.extend(reversed(node.children))
    return counts


def _extract_from_def(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    package: str = "",
) -> None:
    # Java: class_declaration, interface_declaration, enum_declaration,
    #       annotation_type_declaration, record_declaration
    if n.type in {
        TS_JAVA_CLASS_DECL,
        TS_JAVA_INTERFACE_DECL,
        TS_JAVA_ENUM_DECL,
        TS_JAVA_ANNOTATION_TYPE_DECL,
        TS_JAVA_RECORD_DECL,
    }:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)

        if n.type == TS_JAVA_INTERFACE_DECL:
            kind = NodeKind.INTERFACE
        elif n.type == TS_JAVA_ENUM_DECL:
            kind = NodeKind.ENUM
        elif n.type == TS_JAVA_ANNOTATION_TYPE_DECL:
            kind = NodeKind.INTERFACE  # Annotation types are special interfaces
        elif n.type == TS_JAVA_RECORD_DECL:
            kind = NodeKind.CLASS  # Records are special classes
        else:
            kind = NodeKind.CLASS

        # Extract metadata
        metadata = {}

        annotations = _extract_annotations(src, n)
        if annotations:
            metadata["annotations"] = annotations

        modifiers = _extract_modifiers(src, n)
        if modifiers:
            metadata["modifiers"] = modifiers

        if n.type == TS_JAVA_CLASS_DECL:
            superclass = _extract_superclass(src, n)
            if superclass:
                metadata["extends"] = superclass

        interfaces = _extract_interfaces(src, n)
        if interfaces:
            metadata["implements"] = interfaces

        type_params = _extract_type_parameters(src, n)
        if type_params:
            metadata["type_parameters"] = type_params

        # Mark records
        if n.type == TS_JAVA_RECORD_DECL:
            metadata["is_record"] = True

        symbol = _qualname(ctx, name, package)
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
                language=LANG_JAVA,
                metadata=metadata,
            )
        )

        body = n.child_by_field_name("body")
        if body is not None:
            ctx.push_class(name)
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, package=package)
            ctx.pop_class()
        return

    if n.type in {TS_JAVA_METHOD_DECL, TS_JAVA_CTOR_DECL}:
        name = _get_name(src, n)
        if not name:
            return

        start_line, end_line = _lines(n)

        # Methods inside classes are METHOD, top-level would be FUNCTION (rare in Java)
        kind = NodeKind.METHOD if ctx.class_stack else NodeKind.FUNCTION
        symbol = _qualname(ctx, name, package) if ctx.class_stack else name

        # Extract metadata
        metadata = {}
        metadata.update(_method_metadata(src, n, name=name))

        annotations = _extract_annotations(src, n)
        if annotations:
            metadata["annotations"] = annotations

        modifiers = _extract_modifiers(src, n)
        if modifiers:
            metadata["modifiers"] = modifiers

        # Count lambdas and method references in method body
        body = n.child_by_field_name("body")
        if body:
            functional_counts = _count_lambdas_and_refs(src, body)
            if functional_counts["lambda_count"] > 0:
                metadata["lambda_count"] = functional_counts["lambda_count"]
            if functional_counts["method_ref_count"] > 0:
                metadata["method_ref_count"] = functional_counts["method_ref_count"]

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
                language=LANG_JAVA,
                metadata=metadata,
            )
        )

        if body is not None:
            _walk(path=path, src=src, n=body, ctx=ctx, out=out, package=package)
        return


def _walk(
    *,
    path: str,
    src: bytes,
    n: TSNode,
    ctx: _BaseContext,
    out: list[Node],
    package: str = "",
) -> None:
    for child in n.children:
        if child.type in {
            TS_JAVA_CLASS_DECL,
            TS_JAVA_INTERFACE_DECL,
            TS_JAVA_ENUM_DECL,
            TS_JAVA_ANNOTATION_TYPE_DECL,
            TS_JAVA_RECORD_DECL,
            TS_JAVA_METHOD_DECL,
            TS_JAVA_CTOR_DECL,
        }:
            _extract_from_def(
                path=path, src=src, n=child, ctx=ctx, out=out, package=package
            )
        else:
            if child.child_count:
                _walk(path=path, src=src, n=child, ctx=ctx, out=out, package=package)


def _extract_package(src: bytes, root: TSNode) -> str:
    """Extract the package name from a Java compilation unit."""
    for child in root.children:
        if child.type == "package_declaration":
            for part in child.children:
                if part.type in {"scoped_identifier", "identifier"}:
                    return _node_text(src, part)
    return ""


def parse_java(path: str, *, exclude_tests: bool = False) -> list[Node]:
    p = Path(path)
    src = p.read_bytes()

    parser = Parser(_JAVA_LANGUAGE)
    tree = parser.parse(src)

    package = _extract_package(src, tree.root_node)
    out: list[Node] = []
    _walk(
        path=path.replace("\\", "/"),
        src=src,
        n=tree.root_node,
        ctx=_BaseContext(),
        out=out,
        package=package,
    )
    return out
