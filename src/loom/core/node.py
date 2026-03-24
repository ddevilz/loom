from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class NodeKind(StrEnum):
    FUNCTION = "function"
    MODULE = "module"
    CLASS = "class"
    METHOD = "method"
    INTERFACE = "interface"
    ENUM = "enum"
    TYPE = "type"
    FILE = "file"
    COMMUNITY = "community"

    # ticket
    TICKET = "ticket"

    DOCUMENT = "document"
    SECTION = "section"
    CHAPTER = "chapter"
    SUBSECTION = "subsection"
    PARAGRAPH = "paragraph"


class NodeSource(StrEnum):
    CODE = "code"
    DOC = "doc"
    TICKET = "ticket"


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    source: NodeSource

    name: str
    path: str

    content_hash: str | None = None

    summary: str | None = None
    embedding: list[float] | None = None

    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None

    is_dead_code: bool = False

    community_id: str | None = None

    page_start: int | None = None
    page_end: int | None = None

    depth: int | None = None
    parent_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    # ticket-specific fields (None for code/doc nodes)
    status: str | None = None          # e.g. "open", "closed", "in-progress"
    priority: str | None = None        # e.g. "P0", "high", "medium"
    assignee: str | None = None        # display name or login
    url: str | None = None             # link back to source (GitHub/Jira/Linear)
    external_id: str | None = None     # provider's native key e.g. "PROJ-42", "#99"

    @computed_field
    @property
    def is_code(self) -> bool:
        return self.source == NodeSource.CODE

    @computed_field
    @property
    def is_doc(self) -> bool:
        return self.source == NodeSource.DOC

    @computed_field
    @property
    def is_ticket(self) -> bool:
        return self.source == NodeSource.TICKET

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        exclude = kwargs.pop("exclude", None)
        exclude_set: set[str] = set(exclude) if exclude is not None else set()
        exclude_set.update({"is_code", "is_doc", "is_ticket"})
        return super().model_dump(exclude=exclude_set, **kwargs)

    @model_validator(mode="after")
    def _validate_id_convention(self) -> Node:
        if self.source == NodeSource.DOC:
            if not self.id.startswith("doc:"):
                raise ValueError("Doc node id must start with 'doc:'")
        elif self.source == NodeSource.TICKET:
            if not self.id.startswith("ticket:"):
                raise ValueError("Ticket node id must start with 'ticket:'")
        else:
            expected_prefix = f"{self.kind.value}:"
            if not self.id.startswith(expected_prefix):
                raise ValueError(
                    f"Code node id must start with {expected_prefix!r} (got {self.id!r})"
                )
        return self

    @staticmethod
    def make_code_id(kind: NodeKind, path: str, symbol: str) -> str:
        return f"{kind.value}:{path}:{symbol}"

    @staticmethod
    def make_doc_id(doc_path: str, section_ref: str) -> str:
        return f"doc:{doc_path}:{section_ref}"

    @staticmethod
    def make_ticket_id(provider: str, project: str, key: str) -> str:
        """Create a canonical ticket node ID.

        Args:
            provider: Source system name ("jira", "github", "linear")
            project: Project key or owner/repo (e.g. "PROJ", "owner/repo")
            key: Ticket key or number (e.g. "PROJ-42", "99")

        Returns:
            Canonical node ID string, e.g. "ticket:jira:PROJ/PROJ-42"
        """
        return f"ticket:{provider}:{project}/{key}"
