from __future__ import annotations

import json

from loom.core.edge import Edge, EdgeOrigin, EdgeType
from loom.core.falkor.mappers import serialize_edge_props


def test_serialize_edge_props_includes_origin_and_json_metadata() -> None:
    e = Edge(
        from_id="a",
        to_id="b",
        kind=EdgeType.CALLS,
        origin=EdgeOrigin.COMPUTED,
        confidence=0.5,
        metadata={"x": 1},
    )

    props = serialize_edge_props(e)

    assert props["origin"] == EdgeOrigin.COMPUTED

    meta = props.get("metadata")
    assert isinstance(meta, str)
    assert json.loads(meta) == {"x": 1}
