from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from loom.analysis.code.extractor import extract_summary
from loom.core.context import DB
from loom.core.edge import EdgeType
from loom.store.nodes import row_to_node

_CALLER_LIMIT = 10
_CALLEE_LIMIT = 10
_MEMBER_LIMIT = 20


def _build_packet(
    node_row: sqlite3.Row,
    callers: list[sqlite3.Row],
    callers_total: int,
    callees: list[sqlite3.Row],
    callees_total: int,
) -> dict[str, Any]:
    node = row_to_node(node_row)
    metadata = json.loads(node_row["metadata"]) if node_row["metadata"] else {}

    summary_hash = node_row["summary_hash"] if "summary_hash" in node_row.keys() else None
    content_hash = node_row["content_hash"]
    stale = bool(summary_hash and content_hash and summary_hash != content_hash)

    auto_summary = extract_summary(node)

    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "line": node.start_line,
        "signature": metadata.get("signature"),
        "summary": node.summary,
        "summary_source": "agent" if node.summary else None,
        "summary_stale": stale,
        "auto_summary": auto_summary if (not node.summary or stale) else None,
        "callers": [
            {"id": r["id"], "name": r["name"], "path": r["path"], "line": r["start_line"]}
            for r in callers
        ],
        "callers_total": callers_total,
        "callees": [
            {"id": r["id"], "name": r["name"], "path": r["path"], "line": r["start_line"]}
            for r in callees
        ],
        "callees_total": callees_total,
        "community_id": node.community_id,
        "has_dynamic_dispatch": metadata.get("has_dynamic_dispatch", False),
        "edge_coverage": metadata.get("edge_coverage", "unknown"),
    }


def _build_members_packet(
    node_row: sqlite3.Row,
    members: list[sqlite3.Row],
    members_total: int,
) -> dict[str, Any]:
    node = row_to_node(node_row)
    auto_summary = extract_summary(node)
    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "line": node.start_line,
        "signature": None,
        "summary": node.summary,
        "summary_source": "agent" if node.summary else None,
        "summary_stale": False,
        "auto_summary": auto_summary if not node.summary else None,
        "members": [
            {"id": r["id"], "name": r["name"], "path": r["path"], "kind": r["kind"]}
            for r in members
        ],
        "members_total": members_total,
        "community_id": node.community_id,
        "has_dynamic_dispatch": False,
        "edge_coverage": "none",
    }


async def get_context_packet(db: DB, node_id: str) -> dict[str, Any] | None:
    """Full context packet for a node — everything needed to reason without reading source.

    For function/method nodes: returns summary, signature, callers (top 10), callees (top 10).
    For class/file/community nodes: returns members via CONTAINS edges.

    Args:
        db: Database context.
        node_id: Exact node id (e.g. 'function:src/auth.py:validate_token').

    Returns:
        Context packet dict, or None if node not found.
    """
    def _run() -> dict[str, Any] | None:
        with db._lock:
            conn = db.connect()
            node_row = conn.execute(
                "SELECT * FROM nodes WHERE id = ? AND deleted_at IS NULL", (node_id,)
            ).fetchone()
            if not node_row:
                return None

            kind = node_row["kind"]
            path = node_row["path"]

            if kind in ("function", "method"):
                callers = conn.execute(
                    """
                    SELECT n.id, n.name, n.path, n.start_line,
                           (SELECT COUNT(*) FROM edges e2 WHERE e2.to_id = n.id) AS indeg
                    FROM edges e
                    JOIN nodes n ON n.id = e.from_id
                    WHERE e.to_id = ? AND e.kind = ?
                    ORDER BY CASE WHEN n.path = ? THEN 0 ELSE 1 END, indeg DESC
                    LIMIT ?
                    """,
                    (node_id, EdgeType.CALLS.value, path, _CALLER_LIMIT),
                ).fetchall()
                callers_total = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE to_id = ? AND kind = ?",
                    (node_id, EdgeType.CALLS.value),
                ).fetchone()[0]

                callees = conn.execute(
                    """
                    SELECT n.id, n.name, n.path, n.start_line
                    FROM edges e
                    JOIN nodes n ON n.id = e.to_id
                    WHERE e.from_id = ? AND e.kind = ?
                    ORDER BY CASE WHEN n.path = ? THEN 0 ELSE 1 END
                    LIMIT ?
                    """,
                    (node_id, EdgeType.CALLS.value, path, _CALLEE_LIMIT),
                ).fetchall()
                callees_total = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE from_id = ? AND kind = ?",
                    (node_id, EdgeType.CALLS.value),
                ).fetchone()[0]

                return _build_packet(node_row, callers, callers_total, callees, callees_total)

            else:
                members = conn.execute(
                    """
                    SELECT n.id, n.name, n.path, n.kind
                    FROM edges e
                    JOIN nodes n ON n.id = e.to_id
                    WHERE e.from_id = ? AND e.kind = ?
                    LIMIT ?
                    """,
                    (node_id, EdgeType.CONTAINS.value, _MEMBER_LIMIT),
                ).fetchall()
                members_total = conn.execute(
                    "SELECT COUNT(*) FROM edges WHERE from_id = ? AND kind = ?",
                    (node_id, EdgeType.CONTAINS.value),
                ).fetchone()[0]
                return _build_members_packet(node_row, members, members_total)

    return await asyncio.to_thread(_run)
