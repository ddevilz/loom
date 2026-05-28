"""graph_tagger.py — graph-structure-derived tags.

Computes dead-code, entry-point, hub, and bridge tags from edge structure.
Pure computation — returns dict[node_id, list[tags]]. Caller writes to DB.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.graph.repository import Repository

from loom.indexer.complexity import BRIDGE_MIN_INDEGREE, BRIDGE_MIN_OUTDEGREE


def _get_indegrees(repo: "Repository") -> dict[str, int]:
    """Return {node_id: in_degree} for all non-deleted CALLS edges."""
    conn = repo.db.connect()
    rows = conn.execute(
        """SELECT e.to_id, COUNT(*) AS cnt
           FROM edges e
           JOIN nodes n ON n.id = e.to_id
           WHERE e.kind = 'CALLS' AND n.deleted_at IS NULL
           GROUP BY e.to_id"""
    ).fetchall()
    return {r["to_id"]: r["cnt"] for r in rows}


def _get_outdegrees(repo: "Repository") -> dict[str, int]:
    """Return {node_id: out_degree} for all non-deleted CALLS edges."""
    conn = repo.db.connect()
    rows = conn.execute(
        """SELECT e.from_id, COUNT(*) AS cnt
           FROM edges e
           JOIN nodes n ON n.id = e.from_id
           WHERE e.kind = 'CALLS' AND n.deleted_at IS NULL
           GROUP BY e.from_id"""
    ).fetchall()
    return {r["from_id"]: r["cnt"] for r in rows}


def _get_all_node_ids(repo: "Repository") -> list[str]:
    """Return IDs of all non-deleted function/method nodes."""
    conn = repo.db.connect()
    rows = conn.execute(
        "SELECT id FROM nodes WHERE kind IN ('function', 'method') AND deleted_at IS NULL"
    ).fetchall()
    return [r["id"] for r in rows]


ENTRY_DECORATOR_TAGS = frozenset({"api-endpoint", "async-task", "cli", "hook"})


def compute_graph_tags(repo: "Repository") -> dict[str, list[str]]:
    """Compute dead-code, entry-point, hub, and bridge tags from graph structure.

    Returns dict[node_id -> list[tags]]. Does NOT write to DB — caller handles persistence.

    Run order: must run AFTER AutoTagger (needs decorator tags for entry-point detection)
    and AFTER TestLinker (TESTED_BY edges must exist before dead-code determination).
    """
    tags: dict[str, list[str]] = defaultdict(list)

    in_degrees = _get_indegrees(repo)
    out_degrees = _get_outdegrees(repo)
    all_node_ids = _get_all_node_ids(repo)

    # dead-code: zero in-degree CALLS (no callers), not an entry-point candidate
    for node_id in all_node_ids:
        in_deg = in_degrees.get(node_id, 0)
        if in_deg == 0:
            # Check if it has entry-facing decorator tags (skip — those are intentional)
            node_tags = set(repo.tags.get_tags(node_id))
            if not (node_tags & ENTRY_DECORATOR_TAGS):
                tags[node_id].append("dead-code")

    # entry-point: zero CALLS in-degree + has entry-facing decorator tag
    for node_id in all_node_ids:
        in_deg = in_degrees.get(node_id, 0)
        if in_deg == 0:
            node_tags = set(repo.tags.get_tags(node_id))
            if node_tags & ENTRY_DECORATOR_TAGS:
                tags[node_id].append("entry-point")

    # hub: in-degree > mean + 2σ (use all_node_ids for population stats)
    all_in = [in_degrees.get(nid, 0) for nid in all_node_ids]
    if len(all_in) >= 2:
        mean_in = statistics.mean(all_in)
        stdev_in = statistics.stdev(all_in)
        threshold = mean_in + 2 * stdev_in
        for node_id in all_node_ids:
            if in_degrees.get(node_id, 0) > threshold:
                tags[node_id].append("hub")

    # bridge: in-degree > BRIDGE_MIN AND out-degree > BRIDGE_MIN
    for node_id in all_node_ids:
        in_deg = in_degrees.get(node_id, 0)
        out_deg = out_degrees.get(node_id, 0)
        if in_deg > BRIDGE_MIN_INDEGREE and out_deg > BRIDGE_MIN_OUTDEGREE:
            tags[node_id].append("bridge")

    return dict(tags)
