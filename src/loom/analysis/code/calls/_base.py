from __future__ import annotations

from tree_sitter import Node as TSNode


def node_text(src: bytes, n: TSNode) -> str:
    """Decode a tree-sitter node's source bytes to a string."""
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")
