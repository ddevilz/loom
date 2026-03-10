from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any

from ..edge_model import Edge
from ..node_model import Node, NodeKind, NodeSource


def serialize_node_props(node: Node) -> dict[str, Any]:
    props = {k: v for k, v in node.model_dump().items() if v is not None}
    # FalkorDB only allows primitive property values or arrays of primitives.
    props["metadata"] = json.dumps(props.get("metadata", {}), ensure_ascii=False)
    ch = props.get("content_hash")
    if ch is not None and not isinstance(ch, str):
        props["content_hash"] = str(ch)
    return props


def deserialize_node_props(props: dict[str, Any]) -> dict[str, Any]:
    meta = props.get("metadata")
    if isinstance(meta, str):
        try:
            props["metadata"] = json.loads(meta)
        except Exception:
            props["metadata"] = {}
    return props


def deserialize_edge_props(props: dict[str, Any]) -> dict[str, Any]:
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


def deserialize_metadata_value(metadata: Any) -> dict[str, Any]:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def coerce_row_node_kind(
    raw_kind: Any,
    *,
    fallback: NodeKind,
    allowed_kinds: Collection[NodeKind] | None = None,
    require_valid_kind: bool = False,
) -> NodeKind | None:
    kind_value = raw_kind.value if hasattr(raw_kind, "value") else raw_kind
    if isinstance(kind_value, str):
        try:
            candidate = NodeKind(kind_value)
        except Exception:
            return None if require_valid_kind else fallback
        if allowed_kinds is None or candidate in allowed_kinds:
            return candidate
    return None if require_valid_kind else fallback


def row_to_node(
    row: dict[str, Any],
    *,
    source: NodeSource,
    fallback_kind: NodeKind,
    allowed_kinds: Collection[NodeKind] | None = None,
    allow_embedding: bool = False,
    require_str_id: bool = False,
    require_valid_kind: bool = False,
    summary_must_be_str: bool = False,
) -> Node | None:
    node_id = row.get("id")
    if not isinstance(node_id, str):
        if require_str_id:
            return None
        node_id = str(node_id)
    node_kind = coerce_row_node_kind(
        row.get("kind"),
        fallback=fallback_kind,
        allowed_kinds=allowed_kinds,
        require_valid_kind=require_valid_kind,
    )
    if node_kind is None:
        return None
    summary = row.get("summary")
    return Node(
        id=node_id,
        kind=node_kind,
        source=source,
        name=str(row.get("name") or node_id),
        summary=summary
        if not summary_must_be_str or isinstance(summary, str)
        else None,
        path=str(row.get("path") or ""),
        embedding=row.get("embedding")
        if allow_embedding and isinstance(row.get("embedding"), list)
        else None,
        metadata=deserialize_metadata_value(row.get("metadata")),
    )
