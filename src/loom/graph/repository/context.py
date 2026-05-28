"""ContextRepository — synchronous context and primer layer.

Extracted from src/loom/query/context.py (async) and
src/loom/query/primer.py (async), converted to pure synchronous methods.
"""
from __future__ import annotations

import datetime
import json
import re
import sqlite3
import subprocess
import time
from typing import Any

from loom.graph.db import DB
from loom.graph.models import EdgeType, SummarySource
from loom.graph.repository.nodes import row_to_node

_CALLER_LIMIT = 10
_CALLEE_LIMIT = 10
_MEMBER_LIMIT = 20

_MAX_MODULES = 8
_MAX_HOT_FUNCTIONS = 5
_MAX_ENTRY_POINTS = 5
_MAX_MODULE_FUNCTIONS = 10


# ---------------------------------------------------------------------------
# Helpers (ported from query/context.py)
# ---------------------------------------------------------------------------


def _humanize_ago(ts: int | None) -> str | None:
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
    if stale:
        return "Source changed — re-read and call store_understanding(force=True)"
    if summary_source == SummarySource.AUTO and in_degree > 5:
        return "High-traffic function with only auto-summary — write agent summary"
    if isinstance(edge_coverage, (int, float)) and edge_coverage < 0.5:
        return "Call graph incomplete (dynamic dispatch) — callers list may be missing entries"
    if updated_at is not None and (time.time() - updated_at) > 48 * 3600:
        return "Index is 2+ days old — run: loom analyze ."
    return None


def _git_diff_hint(path: str, start_line: int | None, end_line: int | None) -> str | None:
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


def _brief_packet(node_row: sqlite3.Row) -> dict[str, Any]:
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

    # Deferred import — loom.analysis.code.extractor not yet moved to graph/
    from loom.indexer.extractor import extract_summary  # noqa: PLC0415

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

    from loom.indexer.extractor import extract_summary  # noqa: PLC0415

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


# ---------------------------------------------------------------------------
# Primer helpers (ported from query/primer.py)
# ---------------------------------------------------------------------------


def _extract_module(path: str) -> str:
    parts = path.split("/")
    for part in parts[:-1]:
        if part not in ("src", "lib", "app", "pkg", "loom"):
            return part
    return parts[0] if parts else "(root)"


def _group_by_module(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT path, COUNT(*) AS cnt FROM nodes "
        "WHERE kind IN ('function', 'method') AND deleted_at IS NULL "
        "GROUP BY path"
    ).fetchall()
    modules: dict[str, int] = {}
    for row in rows:
        mod = _extract_module(row["path"])
        modules[mod] = modules.get(mod, 0) + row["cnt"]
    return dict(sorted(modules.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_MODULES])


def _detect_entry_points(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT name FROM nodes
           WHERE kind IN ('function', 'method')
             AND deleted_at IS NULL
             AND (
               name = 'main'
               OR name LIKE 'handle_%'
               OR name LIKE '%_handler'
               OR metadata LIKE '%"framework_hint": "flask_route"%'
               OR metadata LIKE '%"framework_hint": "fastapi_route"%'
             )
           ORDER BY name
           LIMIT ?""",
        (_MAX_ENTRY_POINTS,),
    ).fetchall()
    return [r["name"] for r in rows]


def _get_hot_functions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT n.name, n.path, COUNT(e.id) AS callers
           FROM nodes n
           JOIN edges e ON e.to_id = n.id
           WHERE e.kind = 'CALLS'
             AND n.kind IN ('function', 'method')
             AND n.deleted_at IS NULL
           GROUP BY n.id
           ORDER BY callers DESC
           LIMIT ?""",
        (_MAX_HOT_FUNCTIONS,),
    ).fetchall()
    return [{"name": r["name"], "path": r["path"], "callers": r["callers"]} for r in rows]


def _build_primer_data(conn: sqlite3.Connection) -> dict[str, Any]:
    total_fns = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind IN ('function', 'method') AND deleted_at IS NULL"
    ).fetchone()[0]
    if total_fns == 0:
        return {"empty": True}

    total_files = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'file' AND deleted_at IS NULL"
    ).fetchone()[0]

    lang_rows = conn.execute(
        "SELECT DISTINCT language FROM nodes WHERE language IS NOT NULL AND deleted_at IS NULL"
    ).fetchall()
    languages = [r["language"] for r in lang_rows if r["language"]]

    modules = _group_by_module(conn)
    modules_total = conn.execute(
        "SELECT COUNT(DISTINCT path) FROM nodes "
        "WHERE kind IN ('function', 'method') AND deleted_at IS NULL"
    ).fetchone()[0]

    entry_points = _detect_entry_points(conn)
    hot = _get_hot_functions(conn)

    sig_count = conn.execute(
        "SELECT COUNT(*) FROM nodes "
        "WHERE kind IN ('function', 'method') AND deleted_at IS NULL "
        "AND metadata LIKE '%\"signature\"%'"
    ).fetchone()[0]
    sum_count = conn.execute(
        "SELECT COUNT(*) FROM nodes "
        "WHERE kind IN ('function', 'method') AND deleted_at IS NULL "
        "AND summary IS NOT NULL"
    ).fetchone()[0]

    last_ts = conn.execute("SELECT MAX(updated_at) FROM nodes WHERE deleted_at IS NULL").fetchone()[0]

    return {
        "empty": False,
        "files": total_files,
        "functions": total_fns,
        "languages": languages,
        "modules": modules,
        "modules_total": modules_total,
        "entry_points": entry_points,
        "hot": hot,
        "coverage": {
            "signatures": sig_count,
            "summaries": sum_count,
            "total": total_fns,
        },
        "last_analyzed": last_ts,
    }


def _build_module_detail(conn: sqlite3.Connection, module: str) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT n.name, n.path, n.summary, n.metadata,
                  (SELECT COUNT(*) FROM edges e
                   WHERE e.to_id = n.id AND e.kind = 'CALLS') AS callers
           FROM nodes n
           WHERE n.kind IN ('function', 'method')
             AND n.deleted_at IS NULL
             AND n.path LIKE ?
           ORDER BY callers DESC
           LIMIT ?""",
        (f"%/{module}/%", _MAX_MODULE_FUNCTIONS),
    ).fetchall()

    fns = []
    for r in rows:
        meta = json.loads(r["metadata"]) if r["metadata"] else {}
        sig = meta.get("signature", r["name"])
        fns.append(
            {
                "name": r["name"],
                "signature": sig,
                "callers": r["callers"],
                "summary": (r["summary"] or "")[:60],
            }
        )

    total = conn.execute(
        "SELECT COUNT(*) FROM nodes "
        "WHERE kind IN ('function','method') AND deleted_at IS NULL AND path LIKE ?",
        (f"%/{module}/%",),
    ).fetchone()[0]

    return {"module": module, "functions": fns, "total": total}


def _format_primer(data: dict[str, Any], module: str | None = None) -> str:
    if data.get("empty"):
        return "Repo: not yet analyzed\n→ Run: loom analyze ."

    if module:
        detail = data.get("module_detail", {})
        if not detail or not detail.get("functions"):
            return f"Module '{module}' not found or empty."
        lines = [f"Module: {detail['module']} ({detail['total']} functions)"]
        lines.append("Key functions:")
        for fn in detail["functions"]:
            callers_str = f"[{fn['callers']} callers]" if fn["callers"] else ""
            summary_str = f'"{fn["summary"]}"' if fn["summary"] else ""
            lines.append(f"  {fn['signature']:<40} {callers_str} {summary_str}".rstrip())
        return "\n".join(lines)

    langs = ", ".join(data["languages"]) if data["languages"] else "unknown"
    lines = [f"Repo: ({langs}, {data['files']} files, {data['functions']} functions)"]

    mod_parts = [f"{m}({n}fn)" for m, n in data["modules"].items()]
    modules_total = data.get("modules_total", len(data["modules"]))
    mod_line = "Modules: " + " ".join(mod_parts)
    if modules_total > _MAX_MODULES:
        mod_line += f" ...and {modules_total - _MAX_MODULES} more"
    lines.append(mod_line)

    if data["entry_points"]:
        lines.append("Entry points: " + ", ".join(f"{e}()" for e in data["entry_points"]))

    if data["hot"]:
        hot_parts = [f"{h['name']}() [{h['callers']}]" for h in data["hot"]]
        lines.append("Hot: " + ", ".join(hot_parts))

    cov = data["coverage"]
    if cov["total"]:
        sig_pct = int(cov["signatures"] / cov["total"] * 100)
        sum_pct = int(cov["summaries"] / cov["total"] * 100)
        lines.append(
            f"Signatures: {cov['signatures']}/{cov['total']} ({sig_pct}%) — from tree-sitter"
        )
        lines.append(f"Summaries: {cov['summaries']}/{cov['total']} ({sum_pct}%)")

    if data["last_analyzed"]:
        dt = datetime.datetime.fromtimestamp(data["last_analyzed"], tz=datetime.timezone.utc)
        lines.append(f"Last analyzed: {dt.strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ContextRepository
# ---------------------------------------------------------------------------


class ContextRepository:
    """Synchronous context packet and primer operations."""

    def __init__(self, db: DB) -> None:
        self._db = db

    def get_context_packet(
        self,
        node_id: str,
        *,
        brief: bool = False,
        callers_limit: int = _CALLER_LIMIT,
        callees_limit: int = _CALLEE_LIMIT,
    ) -> dict[str, Any] | None:
        """Full context packet for a node.

        For function/method nodes: returns summary, signature, callers, callees.
        For class/file/community nodes: returns members via CONTAINS edges.

        Args:
            node_id: Exact node id.
            brief: If True, return metadata only (no traversal).
            callers_limit: Max callers to fetch (0 = skip).
            callees_limit: Max callees to fetch (0 = skip).

        Returns:
            Context packet dict, or None if node not found.
        """
        with self._db._lock:
            conn = self._db.connect()
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

    def build_primer(
        self,
        *,
        module: str | None = None,
        as_json: bool = False,
    ) -> str | dict[str, Any]:
        """Build session primer — compressed codebase overview (~200 tokens).

        No LLM calls. Pure SQL aggregation over existing data.

        Args:
            module: Optional module name for drill-down view.
            as_json: Return dict instead of formatted string.

        Returns:
            Formatted string or dict.
        """
        with self._db._lock:
            conn = self._db.connect()
            data = _build_primer_data(conn)
            if not data.get("empty") and module:
                data["module_detail"] = _build_module_detail(conn, module)
        if as_json:
            return data
        return _format_primer(data, module=module)
