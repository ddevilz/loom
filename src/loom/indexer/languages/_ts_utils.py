from __future__ import annotations

from collections.abc import Iterator

from tree_sitter import Node as TSNode


def node_text(src: bytes, n: TSNode) -> str:
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


def get_name(src: bytes, n: TSNode) -> str | None:
    name_node = n.child_by_field_name("name")
    if name_node is None:
        return None
    return node_text(src, name_node)


def lines(n: TSNode) -> tuple[int, int]:
    start_line = n.start_point[0] + 1
    end_line = n.end_point[0] + 1
    return start_line, end_line


def split_params(text: str) -> list[str]:
    raw = text.strip()
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1]
    return [part.strip() for part in raw.split(",") if part.strip()]


def walk_all(node: TSNode) -> Iterator[TSNode]:
    """Yield this node and all descendants depth-first (iterative, no stack limit)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def count_node_type(node: TSNode, type_name: str) -> int:
    """Count descendants (including node itself) matching type_name."""
    return sum(1 for n in walk_all(node) if n.type == type_name)


def has_decorator(node: TSNode, name: str) -> bool:
    """Return True if any decorator child's text contains `name`.

    For Python, pass the `decorated_definition` node (not `function_definition`);
    decorators are not direct children of the inner definition.
    """
    for child in node.children:
        if child.type == "decorator":
            text = child.text.decode("utf-8", errors="replace") if child.text else ""
            if name in text:
                return True
    return False


def has_decorator_prefix(node: TSNode, prefixes: tuple[str, ...]) -> bool:
    """Return True if any decorator (with leading @ stripped) starts with one of prefixes.

    For Python, pass the `decorated_definition` node (not `function_definition`);
    decorators are not direct children of the inner definition.
    """
    for child in node.children:
        if child.type == "decorator":
            text = child.text.decode("utf-8", errors="replace") if child.text else ""
            stripped = text.lstrip("@").strip()
            if any(stripped.startswith(p) for p in prefixes):
                return True
    return False
