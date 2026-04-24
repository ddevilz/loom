from __future__ import annotations

import asyncio
import datetime
import json
import sqlite3
from typing import Any

from loom.core.context import DB

_MAX_MODULES = 8
_MAX_HOT_FUNCTIONS = 5
_MAX_ENTRY_POINTS = 5
_MAX_MODULE_FUNCTIONS = 10


def _extract_module(path: str) -> str:
    """Extract top-level module name from a file path.

    src/loom/core/db.py  → core
    src/loom/mcp/server.py → mcp
    auth/views.py → auth
    """
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
    return dict(
        sorted(modules.items(), key=lambda kv: kv[1], reverse=True)[:_MAX_MODULES]
    )


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
           WHERE e.kind = 'calls'
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

    last_ts = conn.execute(
        "SELECT MAX(updated_at) FROM nodes WHERE deleted_at IS NULL"
    ).fetchone()[0]

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
                  (SELECT COUNT(*) FROM edges e WHERE e.to_id = n.id AND e.kind = 'calls') AS callers
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
        fns.append({
            "name": r["name"],
            "signature": sig,
            "callers": r["callers"],
            "summary": (r["summary"] or "")[:60],
        })

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
        lines.append(f"Signatures: {cov['signatures']}/{cov['total']} ({sig_pct}%) — from tree-sitter")
        lines.append(f"Summaries: {cov['summaries']}/{cov['total']} ({sum_pct}%)")

    if data["last_analyzed"]:
        dt = datetime.datetime.fromtimestamp(data["last_analyzed"])
        lines.append(f"Last analyzed: {dt.strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)


async def build_primer(
    db: DB,
    *,
    module: str | None = None,
    as_json: bool = False,
) -> str | dict[str, Any]:
    """Build session primer — compressed codebase overview (~200 tokens).

    No LLM calls. Pure SQL aggregation over existing data.

    Args:
        db: Database context.
        module: Optional module name for drill-down view.
        as_json: Return dict instead of formatted string.

    Returns:
        Formatted string or dict.
    """
    def _run() -> dict[str, Any]:
        with db._lock:
            conn = db.connect()
            data = _build_primer_data(conn)
            if not data.get("empty") and module:
                data["module_detail"] = _build_module_detail(conn, module)
            return data

    data = await asyncio.to_thread(_run)
    if as_json:
        return data
    return _format_primer(data, module=module)
