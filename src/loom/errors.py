"""All Loom custom exceptions and error types.

This module provides a single location for all error classes used throughout
the Loom codebase. Keeping them centralized makes it easier to:
- Understand the error hierarchy
- Maintain consistent error handling
- Add new error types without duplication
- Import errors from a single location
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# =============================================================================
# Graph/Database Errors
# =============================================================================


class NodeResolutionError(Exception):
    """Raised when a node name cannot be resolved to a unique node ID.

    This occurs when:
    - No node exists with the given name
    - Multiple nodes share the same name (ambiguous)
    """

    def __init__(self, node_name: str, reason: str, found_count: int = 0) -> None:
        self.node_name = node_name
        self.reason = reason
        self.found_count = found_count
        super().__init__(f"Cannot resolve node '{node_name}': {reason}")


class BulkSizeLimitError(ValueError):
    """Raised when a bulk operation exceeds the allowed item count."""

    pass


class GraphConnectionError(Exception):
    """Raised when the database connection fails or is unavailable."""

    pass


class SchemaError(Exception):
    """Raised when there's an issue with the graph schema."""

    pass


class FalkorError(Exception):
    pass


class FalkorConnectionError(FalkorError):
    pass


class FalkorQueryError(FalkorError):
    pass


# =============================================================================
# Node/Edge Validation Errors
# =============================================================================


class NodeValidationError(ValueError):
    """Raised when a node fails validation."""

    pass


class EdgeValidationError(ValueError):
    """Raised when an edge fails validation."""

    pass


class MetadataError(ValueError):
    """Raised when node/edge metadata is invalid."""

    pass


# =============================================================================
# Ingest/Processing Errors
# =============================================================================

IndexPhase = Literal[
    "parse",
    "calls",
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
    """Represents an error during the indexing process.

    Unlike exception classes, this is a dataclass used to track
    non-fatal errors during batch processing.
    """

    path: str
    phase: IndexPhase
    message: str


@dataclass(frozen=True)
class IndexResult:
    """Result of an indexing operation."""

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


class IngestError(Exception):
    """Raised when a critical error occurs during ingestion."""

    pass


class ParserError(Exception):
    """Raised when a file cannot be parsed."""

    pass


class GitError(Exception):
    """Raised when a git operation fails."""

    pass


# =============================================================================
# Integration Errors
# =============================================================================


class JiraIntegrationError(Exception):
    """Raised when Jira integration fails."""

    pass


class ConfluenceIntegrationError(Exception):
    """Raised when Confluence integration fails."""

    pass


class NotionIntegrationError(Exception):
    """Raised when Notion integration fails."""

    pass


class PDFProcessingError(Exception):
    """Raised when PDF processing fails."""

    pass


# =============================================================================
# Embedding/ML Errors
# =============================================================================


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""

    pass


class DimensionMismatchError(ValueError):
    """Raised when embedding dimensions don't match expected values."""

    pass


class RerankerError(Exception):
    """Raised when cross-encoder reranking fails."""

    pass


# =============================================================================
# MCP Server Errors
# =============================================================================


class MCPError(Exception):
    """Raised when an MCP server operation fails."""

    pass


class ToolExecutionError(MCPError):
    """Raised when an MCP tool execution fails."""

    pass


class ConfigurationError(Exception):
    """Raised when there's a configuration issue."""

    pass


class LLMError(Exception):
    """Raised when an LLM operation fails."""

    pass


# =============================================================================
# Utility Functions
# =============================================================================


def append_index_error(
    errors: list[IndexError],
    *,
    path: str,
    phase: str,
    error: Exception,
) -> None:
    """Log and append an indexing error to the error list.

    Args:
        errors: List to append the error to
        path: File path where error occurred
        phase: Indexing phase (e.g., "parse", "embed")
        error: The exception that occurred
    """
    logger.error(
        "Indexing error in phase '%s' for '%s': %s", phase, path, error, exc_info=True
    )
    errors.append(IndexError(path=path, phase=phase, message=str(error)))
