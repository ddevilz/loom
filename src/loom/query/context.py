from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import subprocess
import time
from typing import Any

from loom.analysis.code.extractor import extract_summary
from loom.core.context import DB
from loom.core.edge import EdgeType
from loom.core.enums import SummarySource
from loom.store.nodes import row_to_node


def _humanize_ago(ts: int | None) -> str | None:
    """Convert unix timestamp to human-readable age string."""
    if ts is None:
        return None
    ago = max(0, int(time.time()) - ts)
    if ago < 60:
        return "just now"
    if ago < 3600:
        return f"{ago // 60}m"
    if ago < 86400:
        return f"{ago // 3600}h"
    return f"{ago // 86400}d"


def _compute_suggestion(
    *,
    stale: bool,
    summary_source: SummarySource,
    in_degree: int,
    edge_coverage: object,
    updated_at: int | None,
) -> str | None:
    """Return highest-priority actionable suggestion, or None."""
    if stale:
        return "Source changed — re-read and call store_understanding(force=True)"
    if summary_source == SummarySource.AUTO and in_degree > 5:
        return "High-traffic function with only auto-summary — write agent summary"
    if isinstance(edge_coverage, (int, float)) and edge_coverage < 0.5:
        return "Call graph incomplete (dynamic dispatch) — callers list may be missing entries"
    if updated_at is not None and (time.time() - updated_at) > 48 * 3600:
        return "Index is 2+ days old — run: loom analyze ."
    return None


_CALLER_LIMIT = 10
_CALLEE_LIMIT = 10
_MEMBER_LIMIT = 20


def _brief_packet(node_row: sqlite3.Row) -> dict[str, Any]:
    """Lightweight metadata-only packet — no traversal. Used when brief=True."""
    node = row_to_node(node_row)
    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "language": node.language,
        "summary": node.summary,
        "start_line": node.start_line,
        "end_line": node.end_line,
    }


def _git_diff_hint(path: str, start_line: int | None, end_line: int | None) -> str | None:
    """Summarise what changed in a node's line range since the last commit."""
    if start_line is None or end_line is None:
        return None
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", path],
            capture_output=True,
            text=True,
            timeout=3,
        )
        diff = result.stdout
        if not diff:
            return None
        added = deleted = 0
        in_range = False
        hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
        new_line = 0
        for line in diff.splitlines():
            m = hunk_re.match(line)
            if m:
                new_line = int(m.group(2))
                in_range = new_line <= end_line
                continue
            if line.startswith(("+++", "---", "@@")):
                continue
            if in_range and start_line <= new_line <= end_line:
                if line.startswith("+"):
                    added += 1
                elif line.startswith("-"):
                    deleted += 1
            if not line.startswith("-"):
                new_line += 1
            if new_line > end_line:
                break
        if added == 0 and deleted == 0:
            return None
        parts = []
        if added:
            parts.append(f"+{added} line{'s' if added != 1 else ''}")
        if deleted:
            parts.append(f"-{deleted} line{'s' if deleted != 1 else ''}")
        return ", ".join(parts)
    except Exception:  # noqa: BLE001
        return None


def _build_packet(
    node_row: sqlite3.Row,
    callers: list[sqlite3.Row],
    callers_total: int,
    callees: list[sqlite3.Row],
    callees_total: int,
) -> dict[str, Any]:
    node = row_to_node(node_row)
    metadata = json.loads(node_row["metadata"]) if node_row["metadata"] else {}

    _keys = node_row.keys()
    summary_hash = node_row["summary_hash"] if "summary_hash" in _keys else None  # noqa: SIM118
    content_hash = node_row["content_hash"]
    stale = bool(summary_hash and content_hash and summary_hash != content_hash)
    summary_author: str | None = node_row["summary_author"] if "summary_author" in _keys else None  # noqa: SIM118

    auto_summary = extract_summary(node)

    _updated_at: int | None = node_row["updated_at"] if "updated_at" in _keys else None
    last_analyzed_ago = _humanize_ago(_updated_at)
    suggestion = _compute_suggestion(
        stale=stale,
        summary_source=SummarySource.AGENT if summary_hash else SummarySource.AUTO,
        in_degree=callers_total,
        edge_coverage=metadata.get("edge_coverage", "unknown"),
        updated_at=_updated_at,
    )
    diff_hint = _git_diff_hint(node.path, node.start_line, node.end_line) if stale else None

    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "line": node.start_line,
        "signature": metadata.get("signature"),
        "summary": node.summary,
        "summary_source": SummarySource.AGENT if summary_hash else SummarySource.AUTO,
        "summary_stale": stale,
        "summary_author": summary_author,
        "diff_hint": diff_hint,
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
        "last_analyzed_ago": last_analyzed_ago,
        "suggestion": suggestion,
    }


def _build_members_packet(
    node_row: sqlite3.Row,
    members: list[sqlite3.Row],
    members_total: int,
) -> dict[str, Any]:
    node = row_to_node(node_row)
    _keys = node_row.keys()
    summary_hash = node_row["summary_hash"] if "summary_hash" in _keys else None  # noqa: SIM118
    summary_author: str | None = node_row["summary_author"] if "summary_author" in _keys else None  # noqa: SIM118
    auto_summary = extract_summary(node)

    _updated_at: int | None = node_row["updated_at"] if "updated_at" in _keys else None
    last_analyzed_ago = _humanize_ago(_updated_at)
    suggestion = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT if summary_hash else SummarySource.AUTO,
        in_degree=0,
        edge_coverage="unknown",
        updated_at=_updated_at,
    )

    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "line": node.start_line,
        "signature": None,
        "summary": node.summary,
        "summary_source": SummarySource.AGENT if summary_hash else SummarySource.AUTO,
        "summary_stale": False,
        "summary_author": summary_author,
        "diff_hint": None,
        "auto_summary": auto_summary if not node.summary else None,
        "members": [
            {"id": r["id"], "name": r["name"], "path": r["path"], "kind": r["kind"]}
            for r in members
        ],
        "members_total": members_total,
        "community_id": node.community_id,
        "has_dynamic_dispatch": False,
        "edge_coverage": "none",
        "last_analyzed_ago": last_analyzed_ago,
        "suggestion": suggestion,
    }


async def get_context_packet(
    db: DB,
    node_id: str,
    *,
    brief: bool = False,
    callers_limit: int = _CALLER_LIMIT,
    callees_limit: int = _CALLEE_LIMIT,
) -> dict[str, Any] | None:
    """Full context packet for a node — everything needed to reason without reading source.

    For function/method nodes: returns summary, signature, callers, callees.
    For class/file/community nodes: returns members via CONTAINS edges.

    Args:
        db: Database context.
        node_id: Exact node id (e.g. 'function:src/auth.py:validate_token').
        brief: If True, return metadata only (no traversal). Replaces get_node.
        callers_limit: Max callers to fetch (0 = skip callers entirely).
        callees_limit: Max callees to fetch (0 = skip callees entirely).

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

            if brief:
                return _brief_packet(node_row)

            kind = node_row["kind"]
            path = node_row["path"]

            if kind in ("function", "method"):
                callers: list[sqlite3.Row] = []
                callers_total = 0
                if callers_limit > 0:
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
                        (node_id, EdgeType.CALLS.value, path, callers_limit),
                    ).fetchall()
                    callers_total = conn.execute(
                        "SELECT COUNT(*) FROM edges WHERE to_id = ? AND kind = ?",
                        (node_id, EdgeType.CALLS.value),
                    ).fetchone()[0]

                callees: list[sqlite3.Row] = []
                callees_total = 0
                if callees_limit > 0:
                    callees = conn.execute(
                        """
                        SELECT n.id, n.name, n.path, n.start_line
                        FROM edges e
                        JOIN nodes n ON n.id = e.to_id
                        WHERE e.from_id = ? AND e.kind = ?
                        ORDER BY CASE WHEN n.path = ? THEN 0 ELSE 1 END
                        LIMIT ?
                        """,
                        (node_id, EdgeType.CALLS.value, path, callees_limit),
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
