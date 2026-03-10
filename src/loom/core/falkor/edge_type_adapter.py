"""Storage adapter for EdgeType enum to handle name/value inconsistency.

This adapter follows the Adapter pattern and Dependency Inversion Principle:
- Domain layer uses EdgeType enum with lowercase values (e.g., EdgeType.CALLS = "calls")
- Storage layer requires uppercase relationship types (e.g., :CALLS)
- This adapter bridges the gap without coupling domain logic to storage format

Usage:
    # Convert domain EdgeType to storage format
    storage_name = EdgeTypeAdapter.to_storage(EdgeType.CALLS)  # "CALLS"

    # Convert storage format back to domain EdgeType
    edge_type = EdgeTypeAdapter.from_storage("CALLS")  # EdgeType.CALLS
"""

from __future__ import annotations

from ..edge_model import EdgeType


class EdgeTypeAdapter:
    """
    Adapter for converting between domain EdgeType and storage format.
    """

    # Cache for performance (computed once at module load)
    _STORAGE_TO_DOMAIN: dict[str, EdgeType] = {
        edge_type.name: edge_type for edge_type in EdgeType
    }

    _DOMAIN_TO_STORAGE: dict[EdgeType, str] = {
        edge_type: edge_type.name for edge_type in EdgeType
    }

    @classmethod
    def to_storage(cls, edge_type: EdgeType) -> str:
        """Convert domain EdgeType to storage format (uppercase name).

        Args:
            edge_type: Domain EdgeType enum value

        Returns:
            Uppercase storage format string (e.g., "CALLS")

        Example:
            >>> EdgeTypeAdapter.to_storage(EdgeType.CALLS)
            'CALLS'
        """
        return cls._DOMAIN_TO_STORAGE[edge_type]

    @classmethod
    def from_storage(cls, storage_name: str) -> EdgeType:
        """Convert storage format (uppercase name) to domain EdgeType.

        Args:
            storage_name: Uppercase storage format string (e.g., "CALLS")

        Returns:
            Domain EdgeType enum value

        Raises:
            KeyError: If storage_name doesn't match any EdgeType

        Example:
            >>> EdgeTypeAdapter.from_storage("CALLS")
            EdgeType.CALLS
        """
        return cls._STORAGE_TO_DOMAIN[storage_name]

    @classmethod
    def to_storage_list(cls, edge_types: list[EdgeType]) -> list[str]:
        """Convert list of domain EdgeTypes to storage format.

        Args:
            edge_types: List of domain EdgeType enum values

        Returns:
            List of uppercase storage format strings

        Example:
            >>> EdgeTypeAdapter.to_storage_list([EdgeType.CALLS, EdgeType.IMPORTS])
            ['CALLS', 'IMPORTS']
        """
        return [cls.to_storage(et) for et in edge_types]

    @classmethod
    def is_valid_storage_name(cls, storage_name: str) -> bool:
        """Check if a storage name corresponds to a valid EdgeType.

        Args:
            storage_name: Uppercase storage format string

        Returns:
            True if storage_name maps to a valid EdgeType, False otherwise

        Example:
            >>> EdgeTypeAdapter.is_valid_storage_name("CALLS")
            True
            >>> EdgeTypeAdapter.is_valid_storage_name("INVALID")
            False
        """
        return storage_name in cls._STORAGE_TO_DOMAIN
