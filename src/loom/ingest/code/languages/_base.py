# src/loom/ingest/code/languages/_base.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field

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
