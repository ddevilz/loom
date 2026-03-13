from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

IndexPhase = Literal[
    "parse",
    "calls",
    "calls_global",
    "persist",
    "summarize",
    "link",
    "embed",
    "hash",
    "invalidate",
    "jira",
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


def append_index_error(
    errors: list[IndexError],
    *,
    path: str,
    phase: IndexPhase,
    error: Exception,
) -> None:
    logger.error(
        "Indexing error in phase '%s' for '%s': %s", phase, path, error, exc_info=True
    )
    errors.append(IndexError(path=path, phase=phase, message=str(error)))
