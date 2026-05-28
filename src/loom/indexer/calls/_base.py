"""_base.py — shared base for call tracers.

Contains:
    node_text — tree-sitter node byte decoder
    BaseCallTracer — abstract interface for call tracers (NEW)

Tracers (python.py, typescript.py, java.py) are NOT yet refactored to extend
BaseCallTracer — that happens in a follow-up PR.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tree_sitter import Node as TSNode

from loom.graph.models import Edge, Node


def node_text(src: bytes, n: TSNode) -> str:
    """Decode a tree-sitter node's source bytes to a string."""
    return src[n.start_byte : n.end_byte].decode("utf-8", errors="replace")


class BaseCallTracer(ABC):
    """Shared call extraction skeleton.

    Defines the contract that all call tracer implementations must fulfill.
    Existing tracers (python.py, typescript.py, java.py) are NOT yet refactored
    to extend this class — that happens in a follow-up PR.
    """

    @abstractmethod
    def trace(self, source: bytes, rel_path: str, nodes: list[Node]) -> list[Edge]:
        """Extract call edges from a parsed source file.

        Args:
            source: Raw UTF-8 source bytes.
            rel_path: Relative file path (used for node IDs).
            nodes: Nodes already parsed from this file.

        Returns:
            List of CALLS edges found in source.
        """
        ...

    def _confidence_for(self, call_type: str) -> float:
        """Map call type to confidence score."""
        return {"direct": 1.0, "method": 0.8, "dynamic": 0.5}.get(call_type, 0.5)
