"""Loom core module - graph database abstractions and models."""

from __future__ import annotations

from loom.errors import BulkSizeLimitError, NodeResolutionError

from .edge_model import Edge, EdgeOrigin, EdgeType
from .graph import LoomGraph
from .model import generate_code_id, generate_doc_id
from .node_model import Node, NodeKind, NodeSource
from .symbol_index import FileSymbolIndex, build_file_index, build_name_index

__all__ = [
    "Node",
    "NodeKind",
    "NodeSource",
    "Edge",
    "EdgeOrigin",
    "EdgeType",
    "LoomGraph",
    "FileSymbolIndex",
    "build_file_index",
    "build_name_index",
    "NodeResolutionError",
    "BulkSizeLimitError",
    "generate_code_id",
    "generate_doc_id",
]
