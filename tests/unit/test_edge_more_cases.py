import pytest

from loom.core.edge_model import Edge, EdgeType


def test_confidence_boundary_values_allowed():
    Edge(from_id="a", to_id="b", kind=EdgeType.CALLS, confidence=0.0)
    Edge(from_id="a", to_id="b", kind=EdgeType.CALLS, confidence=1.0)


def test_loom_edge_allows_link_method_without_reason():
    e = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.LOOM_IMPLEMENTS,
        confidence=0.2,
        link_method="embed_match",
        link_reason=None,
    )
    assert e.link_method == "embed_match"
    assert e.link_reason is None


def test_structural_edge_disallows_link_reason_even_if_method_missing():
    with pytest.raises(ValueError):
        Edge(
            from_id="a",
            to_id="b",
            kind=EdgeType.IMPORTS,
            link_reason="should not be allowed",
        )
