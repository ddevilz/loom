"""Validation utilities for Loom's knowledge graph.

This module provides reusable validation functions to ensure
consistent error handling and messaging across the codebase.
"""

from __future__ import annotations

from loom.errors import NodeResolutionError


def validate_full_node_id(node_id: str, context: str = "operation") -> str:
    """Validate that node_id is a full ID and return it.

    Args:
        node_id: Node ID to validate
        context: Context for error message (e.g., "blast_radius", "neighbors")

    Returns:
        The validated node_id (unchanged if valid)

    Raises:
        NodeResolutionError: If node_id is not a full ID

    Examples:
        >>> validate_full_node_id("function:auth.py:validate", "test")
        'function:auth.py:validate'
        >>> validate_full_node_id("validate", "test")
        Traceback (most recent call last):
            ...
        NodeResolutionError: validate requires a full node ID. Got 'validate'. Use format: 'kind:path:name' (e.g., 'function:auth.py:validate')
    """
    if ":" not in node_id:
        raise NodeResolutionError(
            node_id,
            f"{context} requires a full node ID. Got '{node_id}'. "
            f"Use format: 'kind:path:name' (e.g., 'function:auth.py:validate')",
        )
    return node_id


def validate_full_node_id_value(node_id: str) -> str:
    """Validate that node_id is a full ID and return it (using ValueError).

    This is for contexts where ValueError is more appropriate than NodeResolutionError.

    Args:
        node_id: Node ID to validate

    Returns:
        The validated node_id (unchanged if valid)

    Raises:
        ValueError: If node_id is not a full ID
    """
    if ":" not in node_id:
        raise ValueError(
            f"Invalid node ID '{node_id}'. "
            f"Full IDs required in format: 'kind:path:symbol' "
            f"(e.g., 'function:auth.py:validate')"
        )
    return node_id
