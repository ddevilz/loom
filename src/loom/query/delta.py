from __future__ import annotations

import asyncio
import datetime
import json
import sqlite3
from typing import Any

from loom.analysis.code.extractor import extract_summary
from loom.core.context import DB
from loom.store.nodes import _row_to_node

_DEFAULT_LIMIT = 100


def _row_to_mini_packet(row: sqlite3.Row, change_type: str) -> dict[str, Any]:
    node = _row_to_node(row)
    metadata = json.loads(row["metadata"]) if row["metadata"] else {}
    auto_summary = extract_summary(node) if not node.summary else None

    summary_hash = row["summary_hash"] if "summary_hash" in row.keys() else None
    content_hash = row["content_hash"]
    stale = bool(summary_hash and content_hash and summary_hash != content_hash)

    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "kind": node.kind.value,
        "change_type": change_type,
        "summary": node.summary,
        "summary_stale": stale,
        "auto_summary": auto_summary if (stale or not node.summary) else None,
        "signature": metadata.get("signature"),
    }


async def get_delta_payload(
    db: DB,
    *,
    since_ts: int,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Compute what changed since a given Unix timestamp.

    Returns context packets for changed/deleted nodes only.
    If total changes > limit, returns summary mode.

    Prerequisite: bulk_upsert_nodes must only bump updated_at on real content
    changes — otherwise re-analyzing identical files creates false positives.

    Args:
        db: Database context.
        since_ts: Unix timestamp — return nodes with updated_at > this.
        limit: Max changed nodes before switching to summary mode.

    Returns:
        Delta payload dict.
    """
    def _run() -> dict[str, Any]:
        with db._lock:
            conn = db.connect()

            changed_count = conn.execute(
                """SELECT COUNT(*) FROM nodes
                   WHERE updated_at > ?
                     AND deleted_at IS NULL
                     AND kind NOT IN ('file', 'community')""",
                (since_ts,),
            ).fetchone()[0]

            deleted_count = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NOT NULL AND deleted_at > ?",
                (since_ts,),
            ).fetchone()[0]

            total_changed = changed_count + deleted_count

            if total_changed > limit:
                top_paths = conn.execute(
                    """SELECT path, COUNT(*) AS cnt FROM nodes
                       WHERE updated_at > ? AND deleted_at IS NULL
                       GROUP BY path ORDER BY cnt DESC LIMIT 5""",
                    (since_ts,),
                ).fetchall()
                return {
                    "too_many_changes": True,
                    "changed_count": total_changed,
                    "top_changed_paths": [r["path"] for r in top_paths],
                    "summary": (
                        "Major changes across many files since last session. "
                        "Treat this as a fresh start."
                    ),
                    "recommendation": (
                        "Use search_code() and get_context() to explore relevant areas."
                    ),
                }

            changed_rows = conn.execute(
                """SELECT * FROM nodes
                   WHERE updated_at > ?
                     AND deleted_at IS NULL
                     AND kind NOT IN ('file', 'community')
                   ORDER BY updated_at DESC""",
                (since_ts,),
            ).fetchall()

            deleted_rows = conn.execute(
                "SELECT * FROM nodes WHERE deleted_at IS NOT NULL AND deleted_at > ?",
                (since_ts,),
            ).fetchall()

            unchanged_count = conn.execute(
                """SELECT COUNT(*) FROM nodes
                   WHERE updated_at <= ?
                     AND deleted_at IS NULL
                     AND kind NOT IN ('file', 'community')""",
                (since_ts,),
            ).fetchone()[0]

            since_dt = datetime.datetime.fromtimestamp(since_ts, tz=datetime.timezone.utc)

            changed = [_row_to_mini_packet(r, "modified") for r in changed_rows]
            deleted = [
                {"id": r["id"], "path": r["path"], "change_type": "deleted"}
                for r in deleted_rows
            ]

            parts = []
            if changed:
                parts.append(f"{len(changed)} function(s) changed")
            if deleted:
                parts.append(f"{len(deleted)} deleted")
            summary_text = (", ".join(parts) + ".") if parts else "No changes since last session."

            return {
                "since": since_dt.isoformat(),
                "changed": changed,
                "new": [],
                "deleted": deleted,
                "unchanged_count": unchanged_count,
                "summary": summary_text,
            }

    return await asyncio.to_thread(_run)
