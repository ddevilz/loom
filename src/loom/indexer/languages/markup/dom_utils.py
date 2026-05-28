"""dom_utils.py — shared DOM traversal helpers for HTML parsing.

Extracted from ingest/code/languages/html.py to eliminate duplication
and provide a clean utility layer for HTML tree-sitter parsers.
"""

from __future__ import annotations

import re

from tree_sitter import Node as TSNode

from loom.indexer.languages.constants import (
    HTML_ANGULAR_STRUCTURAL_PREFIX,
    HTML_ANGULAR_TWO_WAY_PREFIX,
    HTML_ATTR_NAME,
    HTML_FRAMEWORK_ANGULAR,
    HTML_FRAMEWORK_VUE,
    HTML_VUE_DIRECTIVE_PREFIX,
    TS_HTML_ATTRIBUTE,
    TS_HTML_ATTRIBUTE_NAME,
    TS_HTML_ATTRIBUTE_VALUE,
    TS_HTML_ELEMENT,
    TS_HTML_QUOTED_ATTR_VALUE,
    TS_HTML_START_TAG,
    TS_HTML_TAG_NAME,
)

_FORM_INPUT_TAGS: frozenset[str] = frozenset()  # populated by html.py to avoid circular

_MAX_INPUT_DEPTH = 20
_CUSTOM_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")


def attr_map(start_tag: TSNode, src: bytes) -> dict[str, str]:
    """Extract attribute name→value map from a tree-sitter start_tag node."""
    attrs: dict[str, str] = {}
    for child in start_tag.children:
        if child.type != TS_HTML_ATTRIBUTE:
            continue
        name_node = None
        val_node = None
        for c in child.children:
            if c.type == TS_HTML_ATTRIBUTE_NAME:
                name_node = c
            elif c.type == TS_HTML_QUOTED_ATTR_VALUE:
                for inner in c.children:
                    if inner.type == TS_HTML_ATTRIBUTE_VALUE:
                        val_node = inner
                        break
            elif c.type == TS_HTML_ATTRIBUTE_VALUE:
                val_node = c
        if name_node is not None:
            name = src[name_node.start_byte : name_node.end_byte].decode("utf-8", errors="replace")
            val = (
                src[val_node.start_byte : val_node.end_byte].decode("utf-8", errors="replace")
                if val_node is not None
                else ""
            )
            attrs[name] = val
    return attrs


def get_tag_name(start_tag: TSNode, src: bytes) -> str:
    """Extract lowercase tag name from a tree-sitter start_tag node."""
    for child in start_tag.children:
        if child.type == TS_HTML_TAG_NAME:
            return src[child.start_byte : child.end_byte].decode("utf-8", errors="replace").lower()
    return ""


def slugify(s: str) -> str:
    """Convert a string to a safe node-id slug."""
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s.strip("/")).strip("_") or "root"


def detect_framework(attrs: dict[str, str], tag: str) -> str | None:
    """Detect Angular or Vue from a single element's attributes."""
    for attr_name in attrs:
        if attr_name.startswith(HTML_ANGULAR_STRUCTURAL_PREFIX):
            return HTML_FRAMEWORK_ANGULAR
        if attr_name.startswith(HTML_ANGULAR_TWO_WAY_PREFIX):
            return HTML_FRAMEWORK_ANGULAR
        if attr_name.startswith(HTML_VUE_DIRECTIVE_PREFIX):
            return HTML_FRAMEWORK_VUE
    if _CUSTOM_TAG_RE.match(tag) and tag.startswith("app-"):
        return HTML_FRAMEWORK_ANGULAR
    return None


def collect_form_inputs(
    element: TSNode,
    src: bytes,
    form_input_tags: frozenset[str],
) -> list[str]:
    """Recursively collect input field names from a form element."""
    acc: list[str] = []
    _inputs_recursive(element, src, acc, 0, form_input_tags)
    return acc[:20]


def _inputs_recursive(
    node: TSNode,
    src: bytes,
    acc: list[str],
    depth: int,
    form_input_tags: frozenset[str],
) -> None:
    if depth > _MAX_INPUT_DEPTH:
        return
    for child in node.children:
        if child.type == TS_HTML_ELEMENT:
            inner_start = next((c for c in child.children if c.type == TS_HTML_START_TAG), None)
            if inner_start is not None:
                tag = get_tag_name(inner_start, src)
                if tag in form_input_tags:
                    attrs = attr_map(inner_start, src)
                    name = (
                        attrs.get(HTML_ATTR_NAME)
                        or attrs.get("[name]")
                        or attrs.get("formControlName")
                    )
                    if name:
                        acc.append(name)
            _inputs_recursive(child, src, acc, depth + 1, form_input_tags)
