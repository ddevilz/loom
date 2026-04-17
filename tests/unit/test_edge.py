import pytest

from loom.core.edge import Edge, EdgeOrigin, EdgeType


def test_edgetype_has_required_members():
    required = {
        # code → code
        "CALLS",
        "IMPORTS",
        "EXTENDS",
        "IMPLEMENTS",
        "USES_TYPE",
        "MEMBER_OF",
        "STEP_IN",
        "COUPLED_WITH",
        "CONTAINS",
        # dynamic/reflection
        "DYNAMIC_CALL",
        "REFLECTS_CALL",
        "DYNAMIC_IMPORT",
        "UNRESOLVED_CALL",
        # doc → doc
        "CHILD_OF",
        "REFERENCES",
        # cross-domain
        "LOOM_IMPLEMENTS",
        "LOOM_VIOLATES",
    }
    assert required.issubset(set(EdgeType.__members__.keys()))


def test_edge_confidence_defaults_to_1():
    e = Edge(from_id="a", to_id="b", kind=EdgeType.CALLS)
    assert e.confidence == 1.0


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_edge_confidence_range_validation(confidence: float):
    with pytest.raises(ValueError):
        Edge(from_id="a", to_id="b", kind=EdgeType.CALLS, confidence=confidence)


def test_structural_edges_cannot_have_link_fields():
    with pytest.raises(ValueError):
        Edge(
            from_id="a",
            to_id="b",
            kind=EdgeType.CALLS,
            link_method="name_match",
            link_reason="matched",
        )


def test_loom_edges_allow_optional_link_fields():
    e = Edge(from_id="a", to_id="b", kind=EdgeType.LOOM_IMPLEMENTS)
    assert e.link_method is None
    assert e.link_reason is None

    e2 = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.LOOM_VIOLATES,
        confidence=0.42,
        link_method="llm_match",
        link_reason="LLM judged the function violates the spec",
    )
    assert e2.link_method == "llm_match"
    assert e2.link_reason is not None


def test_loom_edge_link_reason_requires_link_method():
    with pytest.raises(ValueError):
        Edge(
            from_id="a",
            to_id="b",
            kind=EdgeType.LOOM_VIOLATES,
            link_reason="reason without method",
        )


def test_edge_roundtrip_dump_validate():
    e = Edge(
        from_id="function:src/auth.py:validate_user",
        to_id="doc:spec.pdf:3.2.4",
        kind=EdgeType.LOOM_IMPLEMENTS,
        confidence=0.7,
        link_method="embed_match",
        link_reason="embedding similarity above threshold",
        metadata={"score": 0.91},
    )

    dumped = e.model_dump()
    e2 = Edge.model_validate(dumped)
    assert e2 == e


def test_edge_origin_default_and_roundtrip():
    e = Edge(from_id="a", to_id="b", kind=EdgeType.CALLS)
    assert e.origin == EdgeOrigin.COMPUTED

    e2 = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.HUMAN,
        link_method="name_match",
        link_reason="confirmed by reviewer",
    )
    dumped = e2.model_dump()
    e3 = Edge.model_validate(dumped)
    assert e3.origin == EdgeOrigin.HUMAN
