from __future__ import annotations

import pytest

from loom.core.edge import ConfidenceTier, Edge, EdgeType


def test_edge_defaults():
    edge = Edge(from_id="function:a.py:f", to_id="function:b.py:g", kind=EdgeType.CALLS)
    assert edge.confidence == 1.0
    assert edge.confidence_tier == ConfidenceTier.EXTRACTED


def test_edge_confidence_bounds():
    with pytest.raises(ValueError):
        Edge(from_id="a", to_id="b", kind=EdgeType.CALLS, confidence=1.5)
    with pytest.raises(ValueError):
        Edge(from_id="a", to_id="b", kind=EdgeType.CALLS, confidence=-0.1)


def test_confidence_tier_inferred():
    edge = Edge(
        from_id="function:a.py:f",
        to_id="function:b.py:g",
        kind=EdgeType.CALLS,
        confidence=0.7,
        confidence_tier=ConfidenceTier.INFERRED,
    )
    assert edge.confidence_tier == ConfidenceTier.INFERRED


def test_dropped_edge_types_absent():
    for removed in (
        "IMPLEMENTS",
        "USES_TYPE",
        "STEP_IN",
        "DYNAMIC_CALL",
        "REFLECTS_CALL",
        "DYNAMIC_IMPORT",
        "UNRESOLVED_CALL",
        "LOOM_IMPLEMENTS",
        "LOOM_VIOLATES",
        "REALIZES",
        "CLOSES",
        "VERIFIED_BY",
        "DEPENDS_ON",
    ):
        assert not hasattr(EdgeType, removed), f"{removed} should be removed"


def test_kept_edge_types_present():
    for kept in (
        "CALLS",
        "CONTAINS",
        "COUPLED_WITH",
    ):
        assert hasattr(EdgeType, kept)


def test_dead_edge_types_absent():
    for removed in (
        "EXTENDS",
        "IMPORTS",
        "MEMBER_OF",
        "CHILD_OF",
        "REFERENCES",
    ):
        assert not hasattr(EdgeType, removed), f"{removed} should have been removed (never produced by pipeline)"
