from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any, cast

from ..edge import Edge
from ..node import Node, NodeKind, NodeSource


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _deserialize_props(props: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(props)
    normalized["metadata"] = _parse_metadata(normalized.get("metadata"))
    return normalized


_EPHEMERAL_NODE_FIELDS = frozenset({"depth", "parent_id"})


def serialize_node_props(node: Node) -> dict[str, Any]:
    props = {
        k: v
        for k, v in node.model_dump().items()
        if v is not None and k not in _EPHEMERAL_NODE_FIELDS
    }
    # FalkorDB only allows primitive property values or arrays of primitives.
    props["metadata"] = json.dumps(props.get("metadata", {}), ensure_ascii=False)
    ch = props.get("content_hash")
    if ch is not None and not isinstance(ch, str):
        props["content_hash"] = str(ch)
    return props


def deserialize_node_props(props: dict[str, Any]) -> dict[str, Any]:
    return _deserialize_props(props)


def deserialize_edge_props(props: dict[str, Any]) -> dict[str, Any]:
    return _deserialize_props(props)


def serialize_edge_props(edge: Edge) -> dict[str, Any]:
    props = {
        k: v
        for k, v in edge.model_dump(exclude={"from_id", "to_id", "kind"}).items()
        if v is not None
    }
    props["metadata"] = json.dumps(props.get("metadata", {}), ensure_ascii=False)
    return props


def deserialize_metadata_value(metadata: Any) -> dict[str, Any]:
    return _parse_metadata(metadata)


def coerce_row_node_kind(
    raw_kind: Any,
    *,
    fallback: NodeKind,
    allowed_kinds: Collection[NodeKind] | None = None,
    require_valid_kind: bool = False,
) -> NodeKind | None:
    kind_value = raw_kind.value if hasattr(raw_kind, "value") else raw_kind
    candidate = (
        NodeKind._value2member_map_.get(kind_value)
        if isinstance(kind_value, str)
        else None
    )
    if candidate is not None and (allowed_kinds is None or candidate in allowed_kinds):
        return cast(NodeKind, candidate)
    return None if require_valid_kind else cast(NodeKind, fallback)


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
        status=row.get("status") if isinstance(row.get("status"), str) else None,
        priority=row.get("priority") if isinstance(row.get("priority"), str) else None,
        assignee=row.get("assignee") if isinstance(row.get("assignee"), str) else None,
        url=row.get("url") if isinstance(row.get("url"), str) else None,
        external_id=row.get("external_id")
        if isinstance(row.get("external_id"), str)
        else None,
    )
