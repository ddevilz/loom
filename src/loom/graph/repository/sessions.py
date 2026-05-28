"""SessionRepository — synchronous session and node-visit persistence layer.

Extracted from:
  - src/loom/store/sessions.py (async) — session CRUD + prune
  - src/loom/store/node_visits.py (async) — visit recording + annotation gaps
  - src/loom/query/delta.py (async) — delta payload computation

All async wrappers removed; methods run synchronously under self._db._lock.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import time
from typing import Any
from uuid import uuid4

from loom.analysis.code.extractor import extract_summary
from loom.graph.db import DB
from loom.graph.repository.nodes import row_to_node


class SessionRepository:
    """Synchronous session, node-visit, and delta operations."""

    def __init__(self, db: DB) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create(self, agent_id: str = "default") -> dict[str, Any]:
        """Create a new session record.

        Args:
            agent_id: Identifier for agent type (e.g. 'claude-code', 'cursor').

        Returns:
            Dict with session_id, agent_id, started_at.
        """
        sid = str(uuid4())
        started_at = int(time.time())

        with self._db._lock:
            conn = self._db.connect()
            conn.execute(
                "INSERT INTO sessions (id, agent_id, started_at) VALUES (?, ?, ?)",
                (sid, agent_id, started_at),
            )
            conn.commit()

        return {"session_id": sid, "agent_id": agent_id, "started_at": started_at}

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Fetch a session record by id.

        Args:
            session_id: UUID returned by create().

        Returns:
            Session dict or None if not found.
        """
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute(
                "SELECT id, agent_id, started_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            return {"id": row["id"], "agent_id": row["agent_id"], "started_at": row["started_at"]}

    def get_latest_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Find the most recent session for an agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            Most recent session dict or None if no sessions exist.
        """
        with self._db._lock:
            conn = self._db.connect()
            row = conn.execute(
                "SELECT id, agent_id, started_at FROM sessions "
                "WHERE agent_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
            if not row:
                return None
            return {"id": row["id"], "agent_id": row["agent_id"], "started_at": row["started_at"]}

    def prune(self, keep: int = 20) -> int:
        """Delete old sessions, keeping the most recent N per agent.

        Args:
            keep: Number of sessions to keep per agent_id.

        Returns:
            Number of sessions deleted.
        """
        with self._db._lock:
            conn = self._db.connect()
            agents = [
                r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM sessions").fetchall()
            ]
            deleted = 0
            for agent_id in agents:
                keep_ids = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM sessions WHERE agent_id = ? "
                        "ORDER BY started_at DESC LIMIT ?",
                        (agent_id, keep),
                    ).fetchall()
                ]
                if not keep_ids:
                    continue
                ph = ",".join("?" * len(keep_ids))
                cur = conn.execute(
                    f"DELETE FROM sessions WHERE agent_id = ? AND id NOT IN ({ph})",
                    (agent_id, *keep_ids),
                )
                deleted += cur.rowcount
            # Cascade-delete visits whose sessions were just pruned
            conn.execute(
                "DELETE FROM node_visits WHERE session_id NOT IN (SELECT id FROM sessions)"
            )
            conn.commit()
        return deleted

    # ------------------------------------------------------------------
    # Node visits
    # ------------------------------------------------------------------

    def record_visit(self, session_id: str, node_id: str, tool: str) -> None:
        """Record that an agent read node_id during session_id via tool.

        Args:
            session_id: Session UUID.
            node_id: Node that was read.
            tool: Tool name used to access the node.
        """
        ts = int(time.time())
        with self._db._lock:
            conn = self._db.connect()
            conn.execute(
                "INSERT INTO node_visits (session_id, node_id, tool, visited_at) VALUES (?,?,?,?)",
                (session_id, node_id, tool, ts),
            )
            conn.commit()

    def get_unannotated_reads(self, session_id: str) -> list[dict[str, Any]]:
        """Nodes read in session_id that have no AGENT summary or a stale one.

        A summary is stale when summary_hash != content_hash (code changed since written).
        Returns rows ordered by last visit time descending.

        Args:
            session_id: Session UUID to query visits for.

        Returns:
            List of node dicts with annotation status.
        """
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                """SELECT nv.node_id, n.name, n.path, n.kind,
                          MAX(nv.visited_at) AS last_visited,
                          MAX(nv.tool) AS last_tool,
                          n.summary_hash,
                          n.content_hash
                     FROM node_visits nv
                     JOIN nodes n ON n.id = nv.node_id
                    WHERE nv.session_id = ?
                      AND n.deleted_at IS NULL
                      AND (
                            n.summary_hash IS NULL
                            OR (n.content_hash IS NOT NULL AND n.summary_hash != n.content_hash)
                          )
                    GROUP BY nv.node_id
                    ORDER BY last_visited DESC""",
                (session_id,),
            ).fetchall()
            return [
                {
                    "node_id": r["node_id"],
                    "name": r["name"],
                    "path": r["path"],
                    "kind": r["kind"],
                    "last_visited": r["last_visited"],
                    "last_tool": r["last_tool"],
                    "stale": r["summary_hash"] is not None,  # has summary but it's stale
                }
                for r in rows
            ]

    def get_annotation_gaps(self, limit: int = 5) -> list[dict[str, Any]]:
        """Top nodes by visit count across ALL sessions that still have no AGENT summary.

        High visit count = agent keeps re-reading without retaining understanding.
        These are the highest-value annotation targets.

        Args:
            limit: Max nodes to return.

        Returns:
            List of node dicts with visit counts.
        """
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                """SELECT nv.node_id, n.name, n.path, n.kind, COUNT(*) AS visit_count
                     FROM node_visits nv
                     JOIN nodes n ON n.id = nv.node_id
                    WHERE n.deleted_at IS NULL
                      AND (
                            n.summary_hash IS NULL
                            OR (n.content_hash IS NOT NULL AND n.summary_hash != n.content_hash)
                          )
                    GROUP BY nv.node_id
                    ORDER BY visit_count DESC
                    LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                {
                    "node_id": r["node_id"],
                    "name": r["name"],
                    "path": r["path"],
                    "kind": r["kind"],
                    "visit_count": r["visit_count"],
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Delta computation
    # ------------------------------------------------------------------

    def get_delta(self, since_ts: int, limit: int = 100) -> dict[str, Any]:
        """Compute what changed since a given Unix timestamp.

        Returns context packets for changed/deleted nodes only.
        If total changes > limit, returns summary mode.

        Prerequisite: bulk_upsert_nodes must only bump updated_at on real content
        changes — otherwise re-analyzing identical files creates false positives.

        Args:
            since_ts: Unix timestamp — return nodes with updated_at > this.
            limit: Max changed nodes before switching to summary mode.

        Returns:
            Delta payload dict.
        """
        with self._db._lock:
            conn = self._db.connect()

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

            changed = [self._row_to_mini_packet(r, "modified") for r in changed_rows]
            deleted = [
                {"id": r["id"], "path": r["path"], "change_type": "deleted"} for r in deleted_rows
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

    def _row_to_mini_packet(self, row: sqlite3.Row, change_type: str) -> dict[str, Any]:
        """Convert a nodes row to a compact delta packet."""
        node = row_to_node(row)
        metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        auto_summary = extract_summary(node) if not node.summary else None

        summary_hash = row["summary_hash"] if "summary_hash" in row.keys() else None  # noqa: SIM118
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
