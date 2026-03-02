from __future__ import annotations

import json
from typing import Any

from ..edge import Edge
from ..node import Node


def serialize_node_props(node: Node) -> dict[str, Any]:
    props = {k: v for k, v in node.model_dump().items() if v is not None}
    # FalkorDB only allows primitive property values or arrays of primitives.
    props["metadata"] = json.dumps(props.get("metadata", {}), ensure_ascii=False)
    return props


def deserialize_node_props(props: dict[str, Any]) -> dict[str, Any]:
    meta = props.get("metadata")
    if isinstance(meta, str):
        try:
            props["metadata"] = json.loads(meta)
        except Exception:
            props["metadata"] = {}
    return props


def serialize_edge_props(edge: Edge) -> dict[str, Any]:
    props = {
        k: v
        for k, v in edge.model_dump(exclude={"from_id", "to_id", "kind"}).items()
        if v is not None
    }
    props["metadata"] = json.dumps(props.get("metadata", {}), ensure_ascii=False)
    return props
