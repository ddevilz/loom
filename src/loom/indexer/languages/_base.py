"""_base.py — shared base classes for language parsers.

Contains:
    _BaseContext — parser state stack (class/function nesting)
    BaseLanguageHandler — abstract interface for tree-sitter parsers (NEW)

Parsers are NOT refactored to extend BaseLanguageHandler yet — that happens
in a follow-up PR. This module defines the interface only.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from loom.graph.models import Node

logger = logging.getLogger(__name__)


@dataclass
class _BaseContext:
    """Shared class/function stack for tree-sitter parsers.

    push/pop are always safe — popping an empty stack emits a warning and
    returns without raising, preventing parser crashes on malformed ASTs.
    """

    class_stack: list[str] = field(default_factory=list)
    fn_stack: list[str] = field(default_factory=list)

    def push_class(self, name: str) -> None:
        self.class_stack.append(name)

    def pop_class(self) -> None:
        if not self.class_stack:
            logger.warning("_BaseContext.pop_class called on empty stack")
            return
        self.class_stack.pop()

    def current_class(self) -> str | None:
        return self.class_stack[-1] if self.class_stack else None

    def push_fn(self, name: str) -> None:
        self.fn_stack.append(name)

    def pop_fn(self) -> None:
        if not self.fn_stack:
            logger.warning("_BaseContext.pop_fn called on empty stack")
            return
        self.fn_stack.pop()

    def current_fn(self) -> str | None:
        return self.fn_stack[-1] if self.fn_stack else None

    def qualified_name(self) -> str:
        parts = []
        if self.class_stack:
            parts.append(self.class_stack[-1])
        if self.fn_stack:
            parts.append(self.fn_stack[-1])
        return ".".join(parts)


class BaseLanguageHandler(ABC):
    """Template method interface for tree-sitter language parsers.

    Defines the contract that all language handlers must fulfill.
    Existing parsers (python.py, typescript.py, etc.) are NOT yet refactored
    to extend this class — that happens in a follow-up PR.
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """The language identifier (e.g. 'python', 'typescript')."""
        ...

    @abstractmethod
    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        """Parse source bytes into a list of Nodes.

        Args:
            source: Raw UTF-8 source bytes.
            rel_path: Relative file path (used for node IDs and paths).

        Returns:
            List of parsed Nodes.
        """
        ...

    def _build_node_id(self, kind: str, path: str, name: str) -> str:
        return f"{kind}:{path}:{name}"

    def _extract_decorators(self, node: object) -> list[str]:
        """Common decorator extraction — override for language-specific behavior."""
        decorators = []
        for child in getattr(node, "children", []):
            if getattr(child, "type", None) in ("decorator", "annotation", "marker_annotation"):
                text = getattr(child, "text", b"")
                if isinstance(text, bytes):
                    decorators.append(text.decode("utf-8", errors="replace").strip())
                else:
                    decorators.append(str(text).strip())
        return decorators
