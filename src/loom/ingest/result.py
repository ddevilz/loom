from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


IndexPhase = Literal[
    "parse",
    "calls",
    "persist",
    "summarize",
    "link",
    "embed",
    "communities",
    "hash",
    "invalidate",
    "jira",
    "coupling",
    "process",
]


@dataclass(frozen=True)
class IndexError:
    path: str
    phase: IndexPhase
    message: str


@dataclass(frozen=True)
class IndexResult:
    node_count: int
    edge_count: int
    file_count: int
    files_skipped: int
    files_updated: int
    files_added: int
    files_deleted: int
    error_count: int
    duration_ms: float
    errors: list[IndexError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
