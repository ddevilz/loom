from __future__ import annotations

from typing import Any

from loom.core import EdgeType
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.protocols import QueryGraph

_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)


def _slug(text: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    parts = [part for part in normalized.split("-") if part]
    return "-".join(parts)


def format_doc_reference(path: str, name: str, kind: str) -> str:
    basename = path.replace("\\", "/").split("/")[-1]
    if kind == "document" or name == basename:
        return basename
    anchor = _slug(name)
    return f"{basename}#{anchor}" if anchor else basename


async def build_blast_radius_payload(
    graph: QueryGraph,
    *,
    node_id: str,
    depth: int,
) -> dict[str, Any]:
    root_rows = await graph.query(
        "MATCH (n:Node {id: $id}) "
        "RETURN n.id AS id, n.name AS name, n.path AS path, n.kind AS kind "
        "LIMIT 1",
        {"id": node_id},
    )
    if not root_rows:
        return {
            "root": None,
            "summary": {"total_nodes": 0, "hops": 0},
            "callers": [],
            "docs_at_risk": [],
            "warnings": [],
        }

    nodes = await graph.blast_radius(node_id, depth=depth)
    doc_rows = await graph.query(
        f"""
MATCH (n:Node {{id: $id}})-[r:{_LOOM_IMPL_REL}]->(d:Node)
RETURN d.id AS id, d.name AS name, d.path AS path, d.kind AS kind,
       r.link_reason AS link_reason
ORDER BY d.path, d.name
""",
        {"id": node_id},
    )

    root = root_rows[0]
    callers = [
        {
            "id": n.id,
            "name": n.name,
            "path": n.path,
            "kind": n.kind.value,
            "depth": n.depth or 0,
            "parent_id": n.parent_id,
            "edge_label": "CALLS",
        }
        for n in nodes
    ]

    docs_at_risk = []
    warnings = []
    for row in doc_rows:
        doc_kind = str(row.get("kind") or "")
        doc_name = str(row.get("name") or "")
        doc_path = str(row.get("path") or "")
        reason = row.get("link_reason")
        if isinstance(reason, str) and reason.strip():
            condition = reason.strip()
        else:
            condition = f"{root['name']}() signature changes"
        doc_ref = format_doc_reference(doc_path, doc_name, doc_kind)
        docs_at_risk.append(
            {
                "id": str(row.get("id") or ""),
                "name": doc_name,
                "path": doc_path,
                "kind": doc_kind,
                "edge_label": "IMPLEMENTS",
                "doc_ref": doc_ref,
                "suffix": " (doc at risk)",
                "condition": condition,
            }
        )
        warnings.append(f"{doc_ref} requires update if {condition}.")

    return {
        "root": {
            "id": str(root["id"]),
            "name": str(root["name"]),
            "path": str(root["path"]),
            "kind": str(root["kind"]),
        },
        "summary": {
            "total_nodes": len(callers) + len(docs_at_risk),
            "hops": max((n.depth or 0) for n in nodes) if nodes else 0,
        },
        "callers": callers,
        "docs_at_risk": docs_at_risk,
        "warnings": warnings,
    }
