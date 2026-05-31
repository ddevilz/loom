"""graph_tagger.py — graph-structure-derived tags.

Computes dead-code, entry-point, hub, and bridge tags from edge structure.
Pure computation — returns dict[node_id, list[tags]]. Caller writes to DB.
"""

from __future__ import annotations

import statistics
from collections import defaultdict, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.graph.repository import Repository

from loom.indexer.complexity import BRANDES_NODE_LIMIT, BRIDGE_MIN_INDEGREE, BRIDGE_MIN_OUTDEGREE


def _compute_bridge_scores(
    node_ids: list[str],
    edges: list[tuple[str, str]],
) -> dict[str, float]:
    """Brandes (2001) betweenness centrality, undirected.

    Returns node_id → normalized score in [0.0, 1.0]. Empty dict if above gate or too small.
    """
    n = len(node_ids)
    if n >= BRANDES_NODE_LIMIT or n < 3:
        return {}

    adj: dict[str, list[str]] = defaultdict(list)
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)

    cb: dict[str, float] = dict.fromkeys(node_ids, 0.0)

    for s in node_ids:
        stack: list[str] = []
        pred: dict[str, list[str]] = defaultdict(list)
        sigma: dict[str, int] = defaultdict(int)
        dist: dict[str, int] = dict.fromkeys(node_ids, -1)
        sigma[s] = 1
        dist[s] = 0
        q: deque[str] = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj[v]:
                if w not in dist:
                    continue  # skip nodes not in our node_ids set (e.g. deleted nodes in edges)
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta: dict[str, float] = defaultdict(float)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]

    # Normalize for undirected: divide by 2 (each pair counted twice) and by (n-1)(n-2)/2
    max_score = (n - 1) * (n - 2) / 2
    if max_score <= 0:
        return cb
    for k in cb:
        cb[k] = (cb[k] / 2) / max_score
    return cb


def _get_degree_stats(repo: Repository) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Single query: (in_degrees, out_degrees, all_function_node_ids)."""
    conn = repo.db.connect()
    rows = conn.execute(
        """SELECT n.id AS node_id,
                  COUNT(CASE WHEN e.to_id   = n.id THEN 1 END) AS in_deg,
                  COUNT(CASE WHEN e.from_id = n.id THEN 1 END) AS out_deg
           FROM nodes n
           LEFT JOIN edges e
               ON (e.to_id = n.id OR e.from_id = n.id)
               AND e.kind = 'CALLS'
           WHERE n.kind IN ('function', 'method') AND n.deleted_at IS NULL
           GROUP BY n.id"""
    ).fetchall()

    in_degrees: dict[str, int] = {}
    out_degrees: dict[str, int] = {}
    all_node_ids: list[str] = []

    for r in rows:
        nid = r["node_id"]
        in_degrees[nid] = r["in_deg"]
        out_degrees[nid] = r["out_deg"]
        all_node_ids.append(nid)

    return in_degrees, out_degrees, all_node_ids


def _get_entry_tags_for_zero_indegree(
    repo: Repository, zero_in_ids: list[str]
) -> dict[str, set[str]]:
    """Bulk-fetch entry-facing tags for zero-in-degree nodes. One query regardless of count."""
    if not zero_in_ids:
        return {}
    conn = repo.db.connect()
    placeholders = ",".join("?" * len(zero_in_ids))
    rows = conn.execute(
        f"SELECT node_id, tag FROM node_tags "
        f"WHERE node_id IN ({placeholders}) "
        f"AND tag IN ('api-endpoint','async-task','cli','hook')",
        zero_in_ids,
    ).fetchall()
    result: dict[str, set[str]] = {nid: set() for nid in zero_in_ids}
    for r in rows:
        result[r["node_id"]].add(r["tag"])
    return result


ENTRY_DECORATOR_TAGS = frozenset({"api-endpoint", "async-task", "cli", "hook"})


def compute_graph_tags(repo: Repository) -> dict[str, list[str]]:
    """Compute dead-code, entry-point, hub, and bridge tags from graph structure.

    Returns dict[node_id -> list[tags]]. Does NOT write to DB — caller handles persistence.

    Run order: must run AFTER AutoTagger (needs decorator tags for entry-point detection).
    TestLinker should run first as a pipeline convention, but TESTED_BY edges do not
    suppress dead-code — a tested function with zero CALLS in-degree is still unreachable
    in production code.
    """
    repo.tags.clear_by_tags(["dead-code", "entry-point", "hub", "bridge"], source="system")

    tags: dict[str, list[str]] = defaultdict(list)

    in_degrees, out_degrees, all_node_ids = _get_degree_stats(repo)

    # dead-code / entry-point: zero CALLS in-degree nodes, classified by entry-facing tags
    zero_in_ids = [nid for nid in all_node_ids if in_degrees.get(nid, 0) == 0]
    entry_tags_map = _get_entry_tags_for_zero_indegree(repo, zero_in_ids)

    for node_id in zero_in_ids:
        has_entry_tag = bool(entry_tags_map.get(node_id, set()) & ENTRY_DECORATOR_TAGS)
        if has_entry_tag:
            tags[node_id].append("entry-point")
        else:
            tags[node_id].append("dead-code")

    # hub: in-degree > mean + 2σ (use all_node_ids for population stats)
    all_in = [in_degrees.get(nid, 0) for nid in all_node_ids]
    if len(all_in) >= 2:
        mean_in = statistics.mean(all_in)
        stdev_in = statistics.stdev(all_in)
        threshold = mean_in + 2 * stdev_in
        for node_id in all_node_ids:
            if in_degrees.get(node_id, 0) > threshold:
                tags[node_id].append("hub")

    # bridge: Brandes betweenness (exact) with degree-heuristic fallback for large graphs
    all_nodes_full = repo.nodes.list_all_undeleted()
    all_node_ids_full = [n.id for n in all_nodes_full]
    edge_pairs = [(e.from_id, e.to_id) for e in repo.edges.get_all()]
    scores = _compute_bridge_scores(all_node_ids_full, edge_pairs)

    if scores:
        values = list(scores.values())
        mean_s = statistics.mean(values) if values else 0.0
        std_s = statistics.stdev(values) if len(values) > 1 else 0.0
        threshold = mean_s + 2 * std_s
        for nid, sc in scores.items():
            repo.nodes.update_bridge_score(nid, sc)
            if sc > threshold and sc > 0:
                tags[nid].append("bridge")
    else:
        # Fallback: degree heuristic when graph exceeds Brandes limit
        for node_id in all_node_ids:
            in_deg = in_degrees.get(node_id, 0)
            out_deg = out_degrees.get(node_id, 0)
            if in_deg > BRIDGE_MIN_INDEGREE and out_deg > BRIDGE_MIN_OUTDEGREE:
                tags[node_id].append("bridge")

    return dict(tags)
