from __future__ import annotations

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
