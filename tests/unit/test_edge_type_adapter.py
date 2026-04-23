"""Unit tests for EdgeTypeAdapter following SOLID principles."""

from __future__ import annotations

import pytest

from loom.core import EdgeType
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter


class TestEdgeTypeAdapterToStorage:
    """Test conversion from domain EdgeType to storage format."""

    def test_converts_calls_to_uppercase(self):
        """Domain EdgeType.CALLS should convert to storage format 'CALLS'."""
        result = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
        assert result == "CALLS"

    def test_converts_imports_to_uppercase(self):
        """Domain EdgeType.IMPORTS should convert to storage format 'IMPORTS'."""
        result = EdgeTypeAdapter.to_storage(EdgeType.IMPORTS)
        assert result == "IMPORTS"

    def test_converts_loom_implements_to_uppercase(self):
        """Domain EdgeType.LOOM_IMPLEMENTS should convert to storage format 'LOOM_IMPLEMENTS'."""
        result = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)
        assert result == "LOOM_IMPLEMENTS"

    def test_converts_all_edge_types(self):
        """All EdgeType enum members should have valid storage format."""
        for edge_type in EdgeType:
            storage_name = EdgeTypeAdapter.to_storage(edge_type)
            assert isinstance(storage_name, str)
            assert storage_name.isupper()
            assert storage_name == edge_type.name


class TestEdgeTypeAdapterFromStorage:
    """Test conversion from storage format to domain EdgeType."""

    def test_converts_uppercase_calls_to_domain(self):
        """Storage format 'CALLS' should convert to domain EdgeType.CALLS."""
        result = EdgeTypeAdapter.from_storage("CALLS")
        assert result == EdgeType.CALLS
        assert result.value == "calls"

    def test_converts_uppercase_imports_to_domain(self):
        """Storage format 'IMPORTS' should convert to domain EdgeType.IMPORTS."""
        result = EdgeTypeAdapter.from_storage("IMPORTS")
        assert result == EdgeType.IMPORTS

    def test_converts_loom_implements_to_domain(self):
        """Storage format 'LOOM_IMPLEMENTS' should convert to domain EdgeType.LOOM_IMPLEMENTS."""
        result = EdgeTypeAdapter.from_storage("LOOM_IMPLEMENTS")
        assert result == EdgeType.LOOM_IMPLEMENTS

    def test_raises_key_error_for_invalid_storage_name(self):
        """Invalid storage format should raise KeyError."""
        with pytest.raises(KeyError):
            EdgeTypeAdapter.from_storage("INVALID_TYPE")

    def test_raises_key_error_for_lowercase_storage_name(self):
        """Lowercase storage format should raise KeyError (must be uppercase)."""
        with pytest.raises(KeyError):
            EdgeTypeAdapter.from_storage("calls")


class TestEdgeTypeAdapterBidirectional:
    """Test bidirectional conversion maintains consistency."""

    def test_roundtrip_domain_to_storage_to_domain(self):
        """Converting domain → storage → domain should return original value."""
        for edge_type in EdgeType:
            storage_name = EdgeTypeAdapter.to_storage(edge_type)
            recovered = EdgeTypeAdapter.from_storage(storage_name)
            assert recovered == edge_type

    def test_roundtrip_storage_to_domain_to_storage(self):
        """Converting storage → domain → storage should return original value."""
        for edge_type in EdgeType:
            original_storage = edge_type.name
            domain = EdgeTypeAdapter.from_storage(original_storage)
            recovered_storage = EdgeTypeAdapter.to_storage(domain)
            assert recovered_storage == original_storage


class TestEdgeTypeAdapterToStorageList:
    """Test batch conversion of EdgeType list to storage format."""

    def test_converts_empty_list(self):
        """Empty list should return empty list."""
        result = EdgeTypeAdapter.to_storage_list([])
        assert result == []

    def test_converts_single_edge_type(self):
        """Single EdgeType should convert to single storage name."""
        result = EdgeTypeAdapter.to_storage_list([EdgeType.CALLS])
        assert result == ["CALLS"]

    def test_converts_multiple_edge_types(self):
        """Multiple EdgeTypes should convert to multiple storage names."""
        result = EdgeTypeAdapter.to_storage_list(
            [
                EdgeType.CALLS,
                EdgeType.IMPORTS,
                EdgeType.LOOM_IMPLEMENTS,
            ]
        )
        assert result == ["CALLS", "IMPORTS", "LOOM_IMPLEMENTS"]

    def test_preserves_order(self):
        """Conversion should preserve input order."""
        edge_types = [EdgeType.LOOM_IMPLEMENTS, EdgeType.CALLS, EdgeType.IMPORTS]
        result = EdgeTypeAdapter.to_storage_list(edge_types)
        assert result == ["LOOM_IMPLEMENTS", "CALLS", "IMPORTS"]


class TestEdgeTypeAdapterIsValidStorageName:
    """Test validation of storage format names."""

    def test_valid_storage_names_return_true(self):
        """All valid EdgeType storage names should return True."""
        for edge_type in EdgeType:
            storage_name = edge_type.name
            assert EdgeTypeAdapter.is_valid_storage_name(storage_name) is True

    def test_invalid_storage_name_returns_false(self):
        """Invalid storage name should return False."""
        assert EdgeTypeAdapter.is_valid_storage_name("INVALID_TYPE") is False

    def test_lowercase_storage_name_returns_false(self):
        """Lowercase storage name should return False."""
        assert EdgeTypeAdapter.is_valid_storage_name("calls") is False

    def test_empty_string_returns_false(self):
        """Empty string should return False."""
        assert EdgeTypeAdapter.is_valid_storage_name("") is False


class TestEdgeTypeAdapterPerformance:
    """Test that adapter uses cached mappings for performance."""

    def test_to_storage_uses_precomputed_cache(self):
        """to_storage should use precomputed cache, not compute on each call."""
        # This test verifies the implementation uses _DOMAIN_TO_STORAGE cache
        assert hasattr(EdgeTypeAdapter, "_DOMAIN_TO_STORAGE")
        assert len(EdgeTypeAdapter._DOMAIN_TO_STORAGE) == len(EdgeType)

    def test_from_storage_uses_precomputed_cache(self):
        """from_storage should use precomputed cache, not compute on each call."""
        # This test verifies the implementation uses _STORAGE_TO_DOMAIN cache
        assert hasattr(EdgeTypeAdapter, "_STORAGE_TO_DOMAIN")
        assert len(EdgeTypeAdapter._STORAGE_TO_DOMAIN) == len(EdgeType)
