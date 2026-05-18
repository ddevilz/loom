from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import tree_sitter_html as _ts_html
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes, content_hash_for_line_span
from loom.ingest.code.languages.constants import (
    HTML_ANGULAR_STRUCTURAL_PREFIX,
    HTML_ANGULAR_TWO_WAY_PREFIX,
    HTML_ARIA_PREFIX,
    HTML_ATTR_ACTION,
    HTML_ATTR_CLASS,
    HTML_ATTR_HREF,
    HTML_ATTR_ID,
    HTML_ATTR_METHOD,
    HTML_ATTR_NAME,
    HTML_ATTR_REL,
    HTML_ATTR_REL_STYLESHEET,
    HTML_ATTR_SRC,
    HTML_DATA_PREFIX,
    HTML_FRAMEWORK_ANGULAR,
    HTML_FRAMEWORK_VUE,
    HTML_TAG_BUTTON,
    HTML_TAG_FORM,
    HTML_TAG_INPUT,
    HTML_TAG_LINK,
    HTML_TAG_SCRIPT,
    HTML_TAG_SELECT,
    HTML_TAG_TEMPLATE,
    HTML_TAG_TEXTAREA,
    HTML_TAG_TITLE,
    HTML_TEMPLATE_REF_PREFIX,
    HTML_VUE_DIRECTIVE_PREFIX,
    LANG_HTML,
    META_ARIA_ATTRIBUTES,
    META_BLOCK_NAMES,
    META_CUSTOM_ELEMENTS,
    META_DATA_ATTRIBUTES,
    META_ELEMENT_IDS,
    META_EVENT_HANDLERS,
    META_FORM_ACTIONS,
    META_FORM_COUNT,
    META_FORM_METHOD,
    META_FRAMEWORK_DIRECTIVES,
    META_HTML_ELEMENT_TYPE,
    META_INPUT_NAMES,
    META_SCRIPTS,
    META_STYLESHEETS,
    META_TEMPLATE_ENGINE,
    META_TEMPLATE_REFS,
    META_TITLE,
    TEMPLATE_EJS,
    TEMPLATE_JINJA2,
    TEMPLATE_PHP,
    TS_HTML_ATTRIBUTE,
    TS_HTML_ATTRIBUTE_NAME,
    TS_HTML_ATTRIBUTE_VALUE,
    TS_HTML_ELEMENT,
    TS_HTML_QUOTED_ATTR_VALUE,
    TS_HTML_RAW_TEXT,
    TS_HTML_SCRIPT_ELEMENT,
    TS_HTML_START_TAG,
    TS_HTML_STYLE_ELEMENT,
    TS_HTML_TAG_NAME,
    TS_HTML_TEXT,
)

logger = logging.getLogger(__name__)

_HTML_LANGUAGE = _Language(_ts_html.language())

_JINJA_RE = re.compile(r"\{\{|\{%")
_EJS_RE = re.compile(r"<%=|<%%")
_PHP_RE = re.compile(r"<\?php", re.IGNORECASE)
_BLOCK_RE = re.compile(r"\{%-?\s*block\s+([\w]+)", re.IGNORECASE)
_TEMPLATE_STRIP_RE = re.compile(r"\{[%{].*?[%}]\}", re.DOTALL)
# Angular v17+ control flow: @if/@for/@switch/@let in text nodes
_NG_CONTROL_FLOW_RE = re.compile(r"@(if|for|switch|let|defer|placeholder|loading|error)\b")
# Vue slot shorthand in text: not needed, handled via attrs

_FORM_INPUT_TAGS = frozenset({HTML_TAG_INPUT, HTML_TAG_SELECT, HTML_TAG_TEXTAREA, HTML_TAG_BUTTON})
_WALK_TYPES = frozenset({TS_HTML_ELEMENT, TS_HTML_SCRIPT_ELEMENT, TS_HTML_STYLE_ELEMENT})

# Custom component heuristic: tag contains '-' and starts with a letter
_CUSTOM_TAG_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)+$")


def _attr_map(start_tag: TSNode, src: bytes) -> dict[str, str]:
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


def _get_tag_name(start_tag: TSNode, src: bytes) -> str:
    for child in start_tag.children:
        if child.type == TS_HTML_TAG_NAME:
            return src[child.start_byte : child.end_byte].decode("utf-8", errors="replace").lower()
    return ""


def _slugify(s: str) -> str:
    # Strip leading/trailing slashes before replacing so "/foo/" → "foo" not "_foo_"
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s.strip("/")).strip("_") or "root"


def _detect_framework(attrs: dict[str, str], tag: str) -> str | None:
    """Detect Angular or Vue from a single element's attributes."""
    for attr_name in attrs:
        if attr_name.startswith(HTML_ANGULAR_STRUCTURAL_PREFIX):
            return HTML_FRAMEWORK_ANGULAR
        if attr_name.startswith(HTML_ANGULAR_TWO_WAY_PREFIX):
            return HTML_FRAMEWORK_ANGULAR
        if attr_name.startswith(HTML_VUE_DIRECTIVE_PREFIX):
            return HTML_FRAMEWORK_VUE
    # Custom web components with Angular-style selector are strong signals
    if _CUSTOM_TAG_RE.match(tag) and tag.startswith("app-"):
        return HTML_FRAMEWORK_ANGULAR
    return None


def _collect_form_inputs(element: TSNode, src: bytes) -> list[str]:
    acc: list[str] = []
    _inputs_recursive(element, src, acc)
    return acc[:20]


_MAX_INPUT_DEPTH = 20


def _inputs_recursive(node: TSNode, src: bytes, acc: list[str], depth: int = 0) -> None:
    if depth > _MAX_INPUT_DEPTH:
        return
    for child in node.children:
        if child.type == TS_HTML_ELEMENT:
            inner_start = next((c for c in child.children if c.type == TS_HTML_START_TAG), None)
            if inner_start is not None:
                tag = _get_tag_name(inner_start, src)
                if tag in _FORM_INPUT_TAGS:
                    attrs = _attr_map(inner_start, src)
                    name = (
                        attrs.get(HTML_ATTR_NAME)
                        or attrs.get("[name]")
                        or attrs.get("formControlName")
                    )
                    if name:
                        acc.append(name)
            _inputs_recursive(child, src, acc, depth + 1)


def _walk(
    node: TSNode,
    src: bytes,
    path: str,
    file_node_id: str,
    nodes: list[Node],
    seen_node_ids: set[str],
    seen_element_ids: set[str],
    meta: dict[str, Any],
) -> None:
    for child in node.children:
        if child.type in _WALK_TYPES:
            start_tag = next((c for c in child.children if c.type == TS_HTML_START_TAG), None)
            if start_tag is None:
                _walk(child, src, path, file_node_id, nodes, seen_node_ids, seen_element_ids, meta)
                continue

            tag = _get_tag_name(start_tag, src)
            attrs = _attr_map(start_tag, src)

            # ── Framework detection ──────────────────────────────────
            if "framework" not in meta:
                fw = _detect_framework(attrs, tag)
                if fw:
                    meta["framework"] = fw

            # ── Title text ───────────────────────────────────────────
            if tag == HTML_TAG_TITLE and META_TITLE not in meta:
                for c in child.children:
                    if c.type == TS_HTML_TEXT:
                        raw = src[c.start_byte : c.end_byte].decode("utf-8", errors="replace")
                        cleaned = _TEMPLATE_STRIP_RE.sub("", raw).strip()
                        if cleaned:
                            meta[META_TITLE] = cleaned[:200]
                        break

            # ── Script src ───────────────────────────────────────────
            if tag == HTML_TAG_SCRIPT:
                src_val = attrs.get(HTML_ATTR_SRC)
                if src_val:
                    meta.setdefault(META_SCRIPTS, []).append(src_val)

            # ── Stylesheet href ──────────────────────────────────────
            is_stylesheet = attrs.get(HTML_ATTR_REL, "").lower() == HTML_ATTR_REL_STYLESHEET
            if tag == HTML_TAG_LINK and is_stylesheet:
                href = attrs.get(HTML_ATTR_HREF)
                if href:
                    meta.setdefault(META_STYLESHEETS, []).append(href)

            # ── Angular/Vue framework directives ─────────────────────
            for attr_name in attrs:
                if attr_name.startswith(HTML_ANGULAR_STRUCTURAL_PREFIX) or attr_name.startswith(
                    HTML_VUE_DIRECTIVE_PREFIX
                ):
                    meta.setdefault(META_FRAMEWORK_DIRECTIVES, []).append(attr_name)

            # ── Angular template reference variables (#ref) ───────────
            for attr_name in attrs:
                if attr_name.startswith(HTML_TEMPLATE_REF_PREFIX) and len(attr_name) > 1:
                    ref_name = attr_name[1:]  # strip #
                    meta.setdefault(META_TEMPLATE_REFS, []).append(ref_name)
                    ref_node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"ref_{ref_name}")
                    if ref_node_id not in seen_node_ids:
                        seen_node_ids.add(ref_node_id)
                        sl = start_tag.start_point[0] + 1
                        el = child.end_point[0] + 1
                        nodes.append(
                            Node(
                                id=ref_node_id,
                                kind=NodeKind.FUNCTION,
                                source=NodeSource.CODE,
                                name=f"#{ref_name}",
                                path=path,
                                content_hash=content_hash_for_line_span(src, sl, el),
                                language=LANG_HTML,
                                start_line=sl,
                                end_line=el,
                                parent_id=file_node_id,
                                metadata={
                                    META_HTML_ELEMENT_TYPE: tag,
                                    "angular_ref": True,
                                },
                            )
                        )

            # ── Angular event bindings (click)="handler()" ──────────
            for attr_name, attr_val in attrs.items():
                if attr_name.startswith("(") and attr_name.endswith(")") and attr_val:
                    event = attr_name[1:-1]
                    meta.setdefault(META_EVENT_HANDLERS, []).append(f"{event}:{attr_val}")

            # ── Custom components (<app-*>, <my-*>, etc.) ────────────
            if _CUSTOM_TAG_RE.match(tag):
                meta.setdefault(META_CUSTOM_ELEMENTS, []).append(tag)
                comp_node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"component_{tag}")
                if comp_node_id not in seen_node_ids:
                    seen_node_ids.add(comp_node_id)
                    sl = start_tag.start_point[0] + 1
                    el = child.end_point[0] + 1
                    # Collect [Input] bindings as props
                    inputs = {
                        k[1:-1]: v
                        for k, v in attrs.items()
                        if k.startswith("[") and k.endswith("]") and not k.startswith("[(")
                    }
                    # Collect (Output) bindings
                    outputs = {
                        k[1:-1]: v
                        for k, v in attrs.items()
                        if k.startswith("(") and k.endswith(")")
                    }
                    comp_meta: dict[str, Any] = {META_HTML_ELEMENT_TYPE: "component", "tag": tag}
                    if inputs:
                        comp_meta["inputs"] = inputs
                    if outputs:
                        comp_meta["outputs"] = outputs
                    nodes.append(
                        Node(
                            id=comp_node_id,
                            kind=NodeKind.FUNCTION,
                            source=NodeSource.CODE,
                            name=tag,
                            path=path,
                            content_hash=content_hash_for_line_span(src, sl, el),
                            language=LANG_HTML,
                            start_line=sl,
                            end_line=el,
                            parent_id=file_node_id,
                            metadata=comp_meta,
                        )
                    )

            # ── Text nodes: Jinja2 blocks + Angular @control-flow ────
            for c in child.children:
                if c.type in (TS_HTML_TEXT, TS_HTML_RAW_TEXT):
                    text = src[c.start_byte : c.end_byte].decode("utf-8", errors="replace")
                    # Jinja2 {% block name %}
                    for m in _BLOCK_RE.finditer(text):
                        block_name = m.group(1)
                        meta.setdefault(META_BLOCK_NAMES, []).append(block_name)
                        block_node_id = Node.make_code_id(
                            NodeKind.FUNCTION, path, f"block_{block_name}"
                        )
                        if block_node_id not in seen_node_ids:
                            seen_node_ids.add(block_node_id)
                            sl = c.start_point[0] + 1
                            el = c.end_point[0] + 1
                            nodes.append(
                                Node(
                                    id=block_node_id,
                                    kind=NodeKind.FUNCTION,
                                    source=NodeSource.CODE,
                                    name=f"block:{block_name}",
                                    path=path,
                                    content_hash=content_hash_for_line_span(src, sl, el),
                                    language=LANG_HTML,
                                    start_line=sl,
                                    end_line=el,
                                    parent_id=file_node_id,
                                    metadata={META_HTML_ELEMENT_TYPE: "template_block"},
                                )
                            )
                    # Angular v17+ @if / @for / @switch
                    for m in _NG_CONTROL_FLOW_RE.finditer(text):
                        cf_name = m.group(1)
                        meta.setdefault(META_FRAMEWORK_DIRECTIVES, []).append(f"@{cf_name}")
                        if "framework" not in meta:
                            meta["framework"] = HTML_FRAMEWORK_ANGULAR

            # ── Form element ─────────────────────────────────────────
            if tag == HTML_TAG_FORM:
                action = attrs.get(HTML_ATTR_ACTION, "")
                method = attrs.get(HTML_ATTR_METHOD, "get").upper()
                meta[META_FORM_COUNT] = meta.get(META_FORM_COUNT, 0) + 1
                if action:
                    meta.setdefault(META_FORM_ACTIONS, []).append(action)

                slug = _slugify(action) if action else str(meta[META_FORM_COUNT])
                # html_form_ prefix avoids collision with id="form_<slug>" on sibling elements
                form_node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"html_form_{slug}")
                if form_node_id in seen_node_ids:
                    logger.debug(
                        "html: duplicate form action %r in %s — extra form node skipped",
                        action or "(unnamed)",
                        path,
                    )
                else:
                    seen_node_ids.add(form_node_id)
                    sl = start_tag.start_point[0] + 1
                    el = child.end_point[0] + 1
                    form_meta: dict[str, Any] = {
                        META_HTML_ELEMENT_TYPE: HTML_TAG_FORM,
                        META_FORM_METHOD: method,
                    }
                    if action:
                        form_meta[META_FORM_ACTIONS] = [action]
                    fg = (
                        attrs.get("formGroup")
                        or attrs.get("[formGroup]")
                        or attrs.get("(ngSubmit)")
                    )
                    if fg:
                        form_meta["angular_form_group"] = fg
                    inputs = _collect_form_inputs(child, src)
                    if inputs:
                        form_meta[META_INPUT_NAMES] = inputs
                    nodes.append(
                        Node(
                            id=form_node_id,
                            kind=NodeKind.FUNCTION,
                            source=NodeSource.CODE,
                            name=f"form[{action}]" if action else f"form_{meta[META_FORM_COUNT]}",
                            path=path,
                            content_hash=content_hash_for_line_span(src, sl, el),
                            language=LANG_HTML,
                            start_line=sl,
                            end_line=el,
                            parent_id=file_node_id,
                            metadata=form_meta,
                        )
                    )

            # ── Element with id ──────────────────────────────────────
            element_id = attrs.get(HTML_ATTR_ID)
            if element_id and element_id not in seen_element_ids:
                seen_element_ids.add(element_id)
                meta.setdefault(META_ELEMENT_IDS, []).append(element_id)

                # html_id_ prefix: prevents collision with code symbols that share the same name
                node_id = Node.make_code_id(NodeKind.FUNCTION, path, f"html_id_{element_id}")
                if node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    sl = start_tag.start_point[0] + 1
                    el = child.end_point[0] + 1
                    el_meta: dict[str, Any] = {META_HTML_ELEMENT_TYPE: tag}
                    classes = [c for c in attrs.get(HTML_ATTR_CLASS, "").split() if c]
                    if classes:
                        el_meta["classes"] = classes[:20]
                    data_attrs = {k: v for k, v in attrs.items() if k.startswith(HTML_DATA_PREFIX)}
                    if data_attrs:
                        el_meta[META_DATA_ATTRIBUTES] = data_attrs
                    aria_attrs = {k: v for k, v in attrs.items() if k.startswith(HTML_ARIA_PREFIX)}
                    if aria_attrs:
                        el_meta[META_ARIA_ATTRIBUTES] = aria_attrs
                    if tag == HTML_TAG_TEMPLATE:
                        el_meta["web_component"] = True
                    nodes.append(
                        Node(
                            id=node_id,
                            kind=NodeKind.FUNCTION,
                            source=NodeSource.CODE,
                            name=element_id,
                            path=path,
                            content_hash=content_hash_for_line_span(src, sl, el),
                            language=LANG_HTML,
                            start_line=sl,
                            end_line=el,
                            parent_id=file_node_id,
                            metadata=el_meta,
                        )
                    )

            _walk(child, src, path, file_node_id, nodes, seen_node_ids, seen_element_ids, meta)

        elif child.child_count > 0:
            _walk(child, src, path, file_node_id, nodes, seen_node_ids, seen_element_ids, meta)


def parse_html(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse HTML/Angular/Vue templates with tree-sitter.

    Extracts as searchable nodes:
    - Elements with id= attributes
    - <form> elements (with action, method, input names)
    - Jinja2/Django {% block name %} template blocks
    - Angular: #templateRef variables, custom components (<app-*>)
    - Angular v17+: @if/@for/@switch control flow blocks
    - Vue: v-* directives (collected in metadata)
    """
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    parser = Parser(_HTML_LANGUAGE)
    tree = parser.parse(src)

    file_node_id = f"{NodeKind.FILE.value}:{path}"
    meta: dict[str, Any] = {}
    nodes: list[Node] = []
    seen_node_ids: set[str] = {file_node_id}
    seen_element_ids: set[str] = set()

    # Template engine detection (fast string scan before AST walk)
    if _JINJA_RE.search(content):
        meta[META_TEMPLATE_ENGINE] = TEMPLATE_JINJA2
    elif _EJS_RE.search(content):
        meta[META_TEMPLATE_ENGINE] = TEMPLATE_EJS
    elif _PHP_RE.search(content):
        meta[META_TEMPLATE_ENGINE] = TEMPLATE_PHP

    _walk(tree.root_node, src, path, file_node_id, nodes, seen_node_ids, seen_element_ids, meta)

    # Deduplicate and trim list metadata
    for key in (
        META_SCRIPTS,
        META_STYLESHEETS,
        META_ELEMENT_IDS,
        META_BLOCK_NAMES,
        META_FORM_ACTIONS,
        META_FRAMEWORK_DIRECTIVES,
        META_CUSTOM_ELEMENTS,
        META_TEMPLATE_REFS,
        META_EVENT_HANDLERS,
    ):
        if key in meta and isinstance(meta[key], list):
            seen: set[str] = set()
            deduped = [x for x in meta[key] if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]
            meta[key] = deduped[:20]

    file_node = Node(
        id=file_node_id,
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_HTML,
        metadata=meta,
    )
    return [file_node, *nodes]
