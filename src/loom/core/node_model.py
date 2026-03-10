"""Node data models for Loom's knowledge graph.

This module contains pure node data definitions with no behavior.
Following Axon's clean separation pattern: data models vs operations.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)


class NodeKind(StrEnum):
    """Node type labels for the knowledge graph."""

    # Code entities
    FUNCTION = "function"
    MODULE = "module"
    CLASS = "class"
    METHOD = "method"
    INTERFACE = "interface"
    ENUM = "enum"
    TYPE = "type"
    FILE = "file"
    COMMUNITY = "community"

    # Documentation entities
    DOCUMENT = "document"
    SECTION = "section"
    CHAPTER = "chapter"
    SUBSECTION = "subsection"
    PARAGRAPH = "paragraph"


class NodeSource(StrEnum):
    """Source domain for nodes."""

    CODE = "code"
    DOC = "doc"


class Node(BaseModel):
    """A node in the knowledge graph representing a code or documentation entity.

    This is a pure data model with no behavior. All operations on nodes
    should be in graph.py or other operation modules.
    """

    model_config = ConfigDict(extra="forbid")

    # Core identity
    id: str
    kind: NodeKind
    source: NodeSource
    name: str
    path: str

    # Content metadata
    content_hash: str | None = None
    summary: str | None = None
    embedding: list[float] | None = None

    # Code-specific fields
    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None
    is_dead_code: bool = False

    # Graph analysis fields
    community_id: str | None = None

    # Doc-specific fields
    page_start: int | None = None
    page_end: int | None = None
    depth: int | None = None
    parent_id: str | None = None

    # Extensibility
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def is_code(self) -> bool:
        """True if this is a code node."""
        return self.source == NodeSource.CODE

    @computed_field
    @property
    def is_doc(self) -> bool:
        """True if this is a documentation node."""
        return self.source == NodeSource.DOC

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """Serialize to dict, excluding computed fields."""
        exclude = kwargs.pop("exclude", None)
        exclude_set: set[str] = set(exclude) if exclude is not None else set()
        exclude_set.update({"is_code", "is_doc"})
        return super().model_dump(exclude=exclude_set, **kwargs)

    @model_validator(mode="after")
    def _validate_id_convention(self) -> Node:
        """Validate that node ID follows the deterministic format."""
        if self.source == NodeSource.DOC:
            if not self.id.startswith("doc:"):
                raise ValueError("Doc node id must start with 'doc:'")
        else:
            expected_prefix = f"{self.kind.value}:"
            if not self.id.startswith(expected_prefix):
                raise ValueError(
                    f"Code node id must start with {expected_prefix!r} (got {self.id!r})"
                )
        return self
