from __future__ import annotations

from .edge_model import Edge, EdgeOrigin, EdgeType, LinkMethod
from .node_model import Node, NodeKind, NodeSource


def generate_code_id(kind: NodeKind, path: str, symbol: str = "") -> str:
    normalized_path = path.replace("\\", "/")
    return f"{kind.value}:{normalized_path}:{symbol}"


def generate_doc_id(doc_path: str, section_ref: str = "") -> str:
    normalized_path = doc_path.replace("\\", "/")
    return f"doc:{normalized_path}:{section_ref}"


__all__ = [
    "Node",
    "NodeKind",
    "NodeSource",
    "Edge",
    "EdgeType",
    "EdgeOrigin",
    "LinkMethod",
    "generate_code_id",
    "generate_doc_id",
]
