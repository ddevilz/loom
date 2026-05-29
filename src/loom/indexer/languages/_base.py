"""_base.py — shared base classes for language parsers.

Contains:
    _BaseContext — parser state stack (class/function nesting)
    BaseLanguageHandler — abstract interface for tree-sitter parsers

All language handlers (python.py, typescript.py, javascript.py, java.py) extend
BaseLanguageHandler and use _build_node for consistent 4-part node ID generation.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from tree_sitter import Node as TSNode

from loom.graph.content_hash import content_hash_for_line_span
from loom.graph.models import Node, NodeKind, NodeSource
from loom.indexer.complexity import classify_complexity
from loom.indexer.languages._ts_utils import lines as _lines

logger = logging.getLogger(__name__)


def _default_repo_name() -> str:
    """Return the repo name from environment, defaulting to 'unknown'."""
    return os.environ.get("LOOM_REPO_NAME", "unknown")


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

    All language handlers (python.py, typescript.py, javascript.py, java.py)
    extend this class and use _build_node for consistent 4-part node ID generation
    (kind:repo:path:symbol).

    repo_name is injected after instantiation or read from LOOM_REPO_NAME env var.
    """

    #: Repo name used in 4-part node IDs.  Defaults to LOOM_REPO_NAME env var
    #: (or "unknown" if unset).  Callers may override after instantiation.
    repo_name: str = "unknown"

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

    @property
    def _repo_name(self) -> str:
        """Return the repo name for use in node IDs.

        Falls back to LOOM_REPO_NAME environment variable if repo_name is still
        at the class-level default of "unknown".
        """
        if self.repo_name != "unknown":
            return self.repo_name
        return _default_repo_name()

    def _build_node(
        self,
        ts_node: TSNode,
        src: bytes,
        path: str,
        *,
        kind: NodeKind,
        name: str,
        symbol: str,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Node:
        """Build a Node with complexity computed from ts_node.

        Args:
            ts_node: Tree-sitter AST node for the function/class.
            src: Raw file source bytes.
            path: Relative file path.
            kind: NodeKind (FUNCTION, METHOD, CLASS, etc.).
            name: Simple name (stored on Node.name).
            symbol: Qualname used in ID — caller's responsibility.
            parent_id: ID of containing node, if any.
            metadata: Language-specific extras (decorators, signature, etc.).
        """
        # Local import avoids circular dep: language_notes → languages._ts_utils →
        # languages.__init__ → _base → language_notes
        from loom.indexer.language_notes import extract_language_notes

        start_line, end_line = _lines(ts_node)
        repo_name = self._repo_name
        return Node(
            id=f"{kind.value}:{repo_name}:{path}:{symbol}",
            kind=kind,
            source=NodeSource.CODE,
            name=name,
            path=path,
            language=self.language_name,
            content_hash=content_hash_for_line_span(src, start_line, end_line),
            start_line=start_line,
            end_line=end_line,
            parent_id=parent_id,
            complexity=classify_complexity(ts_node, self.language_name),
            language_notes=extract_language_notes(ts_node, self.language_name, src),
            metadata=metadata or {},
        )

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
