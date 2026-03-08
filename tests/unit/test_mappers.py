from __future__ import annotations

import json

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.mappers import deserialize_edge_props, deserialize_node_props, serialize_edge_props, serialize_node_props


def test_serialize_node_props_encodes_metadata_and_keeps_content_hash() -> None:
    n = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
        content_hash="abc",
        summary="does x",
        metadata={"a": 1},
    )

    props = serialize_node_props(n)

    assert props["content_hash"] == "abc"
    assert props["summary"] == "does x"
    assert isinstance(props["metadata"], str)
    assert json.loads(props["metadata"]) == {"a": 1}


def test_deserialize_node_props_decodes_metadata_json() -> None:
    props = {
        "id": "function:src/x.py:f",
        "kind": NodeKind.FUNCTION,
        "source": NodeSource.CODE,
        "name": "f",
        "path": "src/x.py",
        "metadata": '{"a": 1}',
    }

    out = deserialize_node_props(dict(props))
    assert out["metadata"] == {"a": 1}


def test_deserialize_edge_props_decodes_metadata_json() -> None:
    props = {
        "origin": EdgeOrigin.HUMAN,
        "confidence": 0.8,
        "metadata": '{"reviewed": true}',
    }

    out = deserialize_edge_props(dict(props))

    assert out["metadata"] == {"reviewed": True}


def test_serialize_node_props_includes_embedding_array() -> None:
    n = Node(
        id="function:src/x.py:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="src/x.py",
        embedding=[0.1, 0.2, 0.3],
        metadata={},
    )
    props = serialize_node_props(n)
    assert props["embedding"] == [0.1, 0.2, 0.3]


def test_serialize_edge_props_excludes_structural_fields_and_encodes_metadata() -> None:
    e = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.CALLS,
        origin=EdgeOrigin.COMPUTED,
        confidence=0.5,
        metadata={"x": 1},
    )

    props = serialize_edge_props(e)

    assert "from_id" not in props
    assert "to_id" not in props
    assert "kind" not in props

    assert props["origin"] == EdgeOrigin.COMPUTED
    assert props["confidence"] == 0.5

    assert isinstance(props["metadata"], str)
    assert json.loads(props["metadata"]) == {"x": 1}


def test_serialize_edge_props_includes_link_fields_for_loom_edges() -> None:
    e = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.LOOM_IMPLEMENTS,
        origin=EdgeOrigin.HUMAN,
        link_method="name_match",
        link_reason="confirmed",
        metadata={},
    )

    props = serialize_edge_props(e)
    assert props["origin"] == EdgeOrigin.HUMAN
    assert props["link_method"] == "name_match"
    assert props["link_reason"] == "confirmed"
