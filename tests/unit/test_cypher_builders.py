"""Tests for core/falkor/cypher.py query builders."""

from __future__ import annotations

import pytest

from loom.core.edge import EdgeType
from loom.core.falkor.cypher import (
    bulk_create_or_update_edges,
    bulk_create_or_update_nodes_with_label,
    create_or_update_edge,
    create_or_update_node_with_label,
)
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.node import NodeKind


def test_create_or_update_edge_uses_rel_type() -> None:
    rel = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
    cypher = create_or_update_edge(rel)
    assert rel in cypher
    # IDs must be parameterized, not interpolated
    assert "$from_id" in cypher
    assert "$to_id" in cypher


def test_create_or_update_edge_all_known_types() -> None:
    for edge_type in EdgeType:
        rel = EdgeTypeAdapter.to_storage(edge_type)
        cypher = create_or_update_edge(rel)
        assert rel in cypher
        assert "$" in cypher  # at least one param


def test_create_or_update_node_with_label_has_merge() -> None:
    for kind in NodeKind:
        label = kind.name.title()
        cypher = create_or_update_node_with_label(label)
        assert "MERGE" in cypher
        assert "$id" in cypher
        assert "$props" in cypher
        assert label in cypher


def test_create_or_update_node_with_label_removes_stale_labels() -> None:
    label = NodeKind.FUNCTION.name.title()
    cypher = create_or_update_node_with_label(label)
    # Should remove all other labels
    for kind in NodeKind:
        other = kind.name.title()
        if other != label:
            assert f"REMOVE n:`{other}`" in cypher


def test_bulk_create_or_update_nodes_with_label_unwinds() -> None:
    label = NodeKind.CLASS.name.title()
    cypher = bulk_create_or_update_nodes_with_label(label)
    assert "UNWIND" in cypher
    assert label in cypher
    assert "$nodes" in cypher


def test_bulk_create_or_update_edges_unwinds() -> None:
    rel = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)
    cypher = bulk_create_or_update_edges(rel)
    assert "UNWIND" in cypher
    assert rel in cypher
    assert "$edges" in cypher


def test_edge_type_adapter_validates_known_types() -> None:
    for edge_type in EdgeType:
        rel = EdgeTypeAdapter.to_storage(edge_type)
        assert EdgeTypeAdapter.is_valid_storage_name(rel)


def test_edge_type_adapter_rejects_unknown() -> None:
    assert not EdgeTypeAdapter.is_valid_storage_name("INJECTED_TYPE")
    assert not EdgeTypeAdapter.is_valid_storage_name("")
    assert not EdgeTypeAdapter.is_valid_storage_name("'; DROP TABLE nodes; --")
