from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .enums import Complexity


class NodeKind(StrEnum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    INTERFACE = "interface"
    ENUM = "enum"
    TYPE = "type"
    FILE = "file"
    COMMUNITY = "community"


class NodeSource(StrEnum):
    CODE = "code"


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    source: NodeSource

    name: str
    path: str

    content_hash: str | None = None
    file_hash: str | None = None
    file_mtime: float | None = None

    summary: str | None = None
    summary_hash: str | None = None
    token_count: int | None = None

    start_line: int | None = None
    end_line: int | None = None
    language: str | None = None

    complexity: Complexity | None = None

    community_id: str | None = None

    depth: int | None = None
    parent_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def is_code(self) -> bool:
        return self.source == NodeSource.CODE

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        exclude = kwargs.pop("exclude", None)
        exclude_set: set[str] = set(exclude) if exclude is not None else set()
        exclude_set.add("is_code")
        return super().model_dump(exclude=exclude_set, **kwargs)

    @model_validator(mode="after")
    def _validate_id_convention(self) -> Node:
        expected_prefix = f"{self.kind.value}:"
        if not self.id.startswith(expected_prefix):
            raise ValueError(f"Node id must start with {expected_prefix!r} (got {self.id!r})")
        return self

    @staticmethod
    def make_code_id(kind: NodeKind, path: str, symbol: str) -> str:
        return f"{kind.value}:{path}:{symbol}"
