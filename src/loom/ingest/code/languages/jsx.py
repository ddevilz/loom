from __future__ import annotations

from typing import Any

from tree_sitter import Node as TSNode

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_for_line_span
from loom.ingest.code.languages.constants import (
    HTML_ARIA_PREFIX,
    HTML_ATTR_CLASS,
    HTML_ATTR_ID,
    HTML_DATA_PREFIX,
    META_ARIA_ATTRIBUTES,
    META_DATA_ATTRIBUTES,
    META_HTML_ELEMENT_TYPE,
    META_JSX_PROPS,
    META_JSX_USAGE,
    META_JSX_USE_COUNT,
    META_JSX_USE_LINES,
    TS_JSX_ATTRIBUTE,
    TS_JSX_EXPRESSION,
    TS_JSX_OPENING_ELEMENT,
    TS_JSX_SELF_CLOSING_ELEMENT,
)

_OPENING_TYPES = frozenset({TS_JSX_OPENING_ELEMENT, TS_JSX_SELF_CLOSING_ELEMENT})


def _tag_name(opening: TSNode, src: bytes) -> tuple[str, bool]:
    """Return (tag_name, is_component). is_component=True for PascalCase or member exprs."""
    for child in opening.children:
        if child.type == "identifier":
            name = src[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            return name, name[0].isupper()
        if child.type in ("member_expression", "nested_identifier"):
            # e.g. <Icons.Star>, <UI.Button>
            raw = src[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            return raw, True
    return "", False


def _attr_values(opening: TSNode, src: bytes) -> dict[str, str]:
    """Extract {prop_name: value_text} from a jsx_opening / self_closing element."""
    attrs: dict[str, str] = {}
    for child in opening.children:
        if child.type != TS_JSX_ATTRIBUTE:
            continue
        name_node = None
        val_text = ""
        for c in child.children:
            if c.type == "property_identifier":
                name_node = c
            elif c.type == "string":
                for inner in c.children:
                    if inner.type == "string_fragment":
                        val_text = src[inner.start_byte : inner.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        break
            elif c.type == TS_JSX_EXPRESSION:
                val_text = src[c.start_byte : c.end_byte].decode("utf-8", errors="replace")
        if name_node is not None:
            name = src[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
            attrs[name] = val_text
    return attrs


def _walk(
    node: TSNode,
    src: bytes,
    path: str,
    language: str,
    components: dict[str, dict[str, Any]],
    id_nodes: dict[str, dict[str, Any]],
) -> None:
    for child in node.children:
        if child.type in _OPENING_TYPES:
            tag, is_component = _tag_name(child, src)
            if not tag:
                _walk(child, src, path, language, components, id_nodes)
                continue

            attrs = _attr_values(child, src)
            line = child.start_point[0] + 1

            if is_component:
                # Accumulate usages — deduplicated per component name per file
                if tag not in components:
                    components[tag] = {"lines": [], "props": set()}
                components[tag]["lines"].append(line)
                # Collect non-event, non-key input props (skip children=, key=, ref=)
                _skip = ("key", "ref", "children")
                for attr_name in attrs:
                    if not attr_name.startswith("on") and attr_name not in _skip:
                        components[tag]["props"].add(attr_name)

            # id= on any element (including components that forward id)
            element_id = attrs.get(HTML_ATTR_ID)
            if element_id and element_id not in id_nodes:
                classes = [c for c in attrs.get(HTML_ATTR_CLASS, "").split() if c]
                data_attrs = {k: v for k, v in attrs.items() if k.startswith(HTML_DATA_PREFIX)}
                aria_attrs = {k: v for k, v in attrs.items() if k.startswith(HTML_ARIA_PREFIX)}
                id_nodes[element_id] = {
                    "tag": tag,
                    "line": line,
                    "classes": classes,
                    "data_attrs": data_attrs,
                    "aria_attrs": aria_attrs,
                }

        _walk(child, src, path, language, components, id_nodes)


def extract_jsx_nodes(
    path: str,
    src: bytes,
    tree_root: TSNode,
    language: str,
    file_node_id: str | None = None,
) -> list[Node]:
    """Walk a TSX/JSX AST and return extra nodes for custom components and id= elements.

    Call this after the main TS/JS parse walk. The returned nodes use the same
    path and language as the parent file so they appear in the same index context.
    """
    components: dict[str, dict[str, Any]] = {}
    id_nodes: dict[str, dict[str, Any]] = {}

    _walk(tree_root, src, path, language, components, id_nodes)

    nodes: list[Node] = []

    # One node per unique custom component usage in this file
    for comp_name, data in components.items():
        lines: list[int] = data["lines"]
        props: list[str] = sorted(data["props"])
        node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"jsx_{comp_name}")
        first_line = lines[0]
        last_line = lines[-1]
        meta: dict[str, Any] = {
            META_JSX_USAGE: True,
            META_JSX_USE_COUNT: len(lines),
            META_JSX_USE_LINES: lines[:50],
        }
        if props:
            meta[META_JSX_PROPS] = props[:20]
        nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name=f"<{comp_name}>",
                path=path,
                content_hash=content_hash_for_line_span(src, first_line, last_line),
                language=language,
                start_line=first_line,
                end_line=last_line,
                parent_id=file_node_id,
                metadata=meta,
            )
        )

    # One node per unique id= value in this file
    # Prefix with jsx_id_ to avoid collision with TS/JS function nodes (e.g. function header()
    # vs <div id="header">) which share the same NodeKind.FUNCTION:{path}:{name} space.
    for element_id, data in id_nodes.items():
        node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"jsx_id_{element_id}")
        line = data["line"]
        el_meta: dict[str, Any] = {META_HTML_ELEMENT_TYPE: data["tag"]}
        if data["classes"]:
            el_meta["classes"] = data["classes"][:20]
        if data["data_attrs"]:
            el_meta[META_DATA_ATTRIBUTES] = data["data_attrs"]
        if data["aria_attrs"]:
            el_meta[META_ARIA_ATTRIBUTES] = data["aria_attrs"]
        nodes.append(
            Node(
                id=node_id,
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name=element_id,
                path=path,
                content_hash=content_hash_for_line_span(src, line, line),
                language=language,
                start_line=line,
                end_line=line,
                parent_id=file_node_id,
                metadata=el_meta,
            )
        )

    return nodes
