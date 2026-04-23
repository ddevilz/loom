from __future__ import annotations

import logging
from pathlib import Path

from loom.core.edge import EdgeType
from loom.core.graph import LoomGraph
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.search import search

logger = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore

_MAX_QUERY = 1000
_MAX_ID = 512


def _clamp_limit(n: int) -> int:
    return max(1, min(n, 100))


def _clamp_depth(d: int) -> int:
    return max(1, min(d, 10))


def _req_text(value: str, *, field: str, max_length: int) -> str:
    v = value.strip()
    if not v:
        raise ValueError(f"{field} must be non-empty")
    if len(v) > max_length:
        raise ValueError(f"{field} must be <= {max_length} characters")
    return v


def build_server(
    db_path: Path | None = None,
    *,
    graph: LoomGraph | None = None,
) -> FastMCP:
    """Build and return the FastMCP server with all 10 tools registered."""
    if FastMCP is None:
        raise RuntimeError("fastmcp not installed — run: uv add fastmcp")
    mcp = FastMCP("loom")
    if graph is None:
        graph = LoomGraph(db_path=db_path)

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> list[dict]:
        """Search nodes by name/summary/path via FTS5 or LIKE."""
        q = _req_text(query, field="query", max_length=_MAX_QUERY)
        results = await search(q, graph, limit=_clamp_limit(limit))
        return [
            {
                "id": r.node.id,
                "name": r.node.name,
                "path": r.node.path,
                "kind": r.node.kind.value,
                "score": r.score,
            }
            for r in results
        ]

    @mcp.tool()
    async def get_node(node_id: str) -> dict | None:
        """Return a single node by id."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        n = await graph.get_node(nid)
        if n is None:
            return None
        return {
            "id": n.id,
            "name": n.name,
            "path": n.path,
            "kind": n.kind.value,
            "language": n.language,
            "summary": n.summary,
            "start_line": n.start_line,
            "end_line": n.end_line,
        }

    @mcp.tool()
    async def get_callers(node_id: str) -> list[dict]:
        """One-hop incoming CALLS — functions that call this node."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await graph.neighbors(
            nid, depth=1, edge_types=[EdgeType.CALLS], direction="in"
        )
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_callees(node_id: str) -> list[dict]:
        """One-hop outgoing CALLS — functions this node calls."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await graph.neighbors(
            nid, depth=1, edge_types=[EdgeType.CALLS], direction="out"
        )
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_blast_radius(node_id: str, depth: int = 3) -> dict:
        """Transitive callers via SQLite recursive CTE (who calls this, transitively)."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        return await build_blast_radius_payload(
            graph, node_id=nid, depth=_clamp_depth(depth)
        )

    @mcp.tool()
    async def get_neighbors(node_id: str, depth: int = 1) -> list[dict]:
        """Generic neighbor traversal across all edge kinds, both directions."""
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        nodes = await graph.neighbors(nid, depth=_clamp_depth(depth))
        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value}
            for n in nodes
        ]

    @mcp.tool()
    async def get_community(community_id: str) -> list[dict]:
        """Return all member nodes of a community cluster."""
        cid = _req_text(community_id, field="community_id", max_length=_MAX_ID)
        nodes = await graph.community_members(cid)
        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value}
            for n in nodes
        ]

    @mcp.tool()
    async def shortest_path(from_id: str, to_id: str) -> list[dict] | None:
        """Shortest directed path on CALLS subgraph, from_id → to_id."""
        fid = _req_text(from_id, field="from_id", max_length=_MAX_ID)
        tid = _req_text(to_id, field="to_id", max_length=_MAX_ID)
        path = await graph.shortest_path(fid, tid)
        if path is None:
            return None
        return [{"id": n.id, "name": n.name, "path": n.path} for n in path]

    @mcp.tool()
    async def graph_stats() -> dict:
        """Node/edge counts broken down by kind."""
        return await graph.stats()

    @mcp.tool()
    async def god_nodes(limit: int = 20) -> list[dict]:
        """Highest in-degree on CALLS subgraph (most-called functions)."""
        pairs = await graph.god_nodes(_clamp_limit(limit))
        return [
            {"id": n.id, "name": n.name, "path": n.path, "in_degree": deg}
            for n, deg in pairs
        ]

    @mcp.tool()
    async def store_understanding_batch(updates: list[dict]) -> dict:
        """Cache summaries for multiple nodes in one call. Max 50 per call.

        Args:
            updates: List of {"node_id": str, "summary": str} dicts.

        Returns:
            {"stored": N, "total": M} — N rows updated out of M submitted.
        """
        batch = updates[:50]
        stored = 0
        for item in batch:
            nid = str(item.get("node_id", "")).strip()
            s = str(item.get("summary", "")).strip()
            if nid and s:
                ok = await graph.update_summary(nid, s)
                if ok:
                    stored += 1
        return {"stored": stored, "total": len(batch)}

    @mcp.tool()
    async def store_understanding(node_id: str, summary: str) -> dict:
        """Persist agent-generated understanding of a node back into the graph.

        Use this after reading a function or class to record what it does —
        the summary becomes searchable and visible to future agents and in
        `loom export` visualisations.

        Args:
            node_id: Exact node ID (e.g. "function:src/auth.py:validate_user").
                     Use search_code first if you only know the name.
            summary: Plain-English description of what this node does, its
                     role in the system, known edge cases, or anything useful
                     for future reasoning. Max 4000 chars.

        Returns:
            {"ok": true, "node_id": "..."} on success.
            {"ok": false, "error": "node not found"} if id unknown.
        """
        nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
        s = _req_text(summary, field="summary", max_length=4000)
        updated = await graph.update_summary(nid, s)
        if not updated:
            return {"ok": False, "error": "node not found"}
        return {"ok": True, "node_id": nid}

    return mcp
