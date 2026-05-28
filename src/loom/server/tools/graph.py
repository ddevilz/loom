"""graph.py — graph traversal MCP tools."""
from __future__ import annotations


def register(mcp: object, db: object, session: dict, cache: object) -> None:
    from loom.query import traversal
    from loom.query.blast_radius import build_blast_radius_payload
    from loom.intelligence.cohesion import get_community_cohesion

    from loom.server.validation import MAX_ID, clamp_depth, clamp_limit, err, ok, validate_text
    from loom.server.enums import ErrorCode

    async def _log(node_id: str, tool: str) -> None:
        from loom.store.node_visits import log_visit

        sid = session.get("id")
        if sid:
            await log_visit(db, session_id=sid, node_id=node_id, tool=tool)

    @mcp.tool()
    async def get_blast_radius(
        node_id: str, depth: int = 3, limit: int = 50, offset: int = 0
    ) -> dict:
        """Transitive callers via SQLite recursive CTE. Paginated."""
        try:
            nid = validate_text(node_id, field="node_id", max_length=MAX_ID)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        await _log(nid, "get_blast_radius")
        d = clamp_depth(depth)
        lim = max(1, min(limit, 200))
        key = cache.make_key("get_blast_radius", nid, depth=d, limit=lim, offset=offset)
        if (hit := cache.get(key)) is not None:
            return hit
        result = ok(
            await build_blast_radius_payload(db, node_id=nid, depth=d, limit=lim, offset=offset)
        )
        cache.set(key, result)
        return result

    @mcp.tool()
    async def get_neighbors(
        node_id: str,
        depth: int = 1,
        limit: int = 20,
        include_summaries: bool = True,
    ) -> dict:
        """Generic neighbor traversal across all edge kinds, both directions.

        Args:
            depth: Hop depth (1-10). Default 1.
            limit: Max neighbors to return (1-100). Default 20.
            include_summaries: Include summary text. Set False for names/paths only.
        """
        try:
            nid = validate_text(node_id, field="node_id", max_length=MAX_ID)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        await _log(nid, "get_neighbors")
        d = clamp_depth(depth)
        lim = clamp_limit(limit)
        key = cache.make_key("get_neighbors", nid, depth=d, limit=lim)
        if (hit := cache.get(key)) is not None:
            return hit
        nodes = await traversal.neighbors(db, nid, depth=d)
        nodes = nodes[:lim]
        if include_summaries:
            result = ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "kind": n.kind.value,
                        "summary": n.summary,
                    }
                    for n in nodes
                ]
            )
        else:
            result = ok(
                [{"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value} for n in nodes]
            )
        cache.set(key, result)
        return result

    @mcp.tool()
    async def get_community(
        community_id: str,
        limit: int = 50,
        include_summaries: bool = True,
    ) -> dict:
        """Return member nodes of a community cluster.

        Args:
            limit: Max members to return (1-100). Default 50.
            include_summaries: Include summary text. Set False for names/paths only.
        """
        try:
            cid = validate_text(community_id, field="community_id", max_length=MAX_ID)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        nodes = await traversal.community_members(db, cid)
        nodes = nodes[: clamp_limit(limit)]
        if include_summaries:
            return ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "kind": n.kind.value,
                        "summary": n.summary,
                    }
                    for n in nodes
                ]
            )
        return ok(
            [{"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value} for n in nodes]
        )

    @mcp.tool()
    async def shortest_path(
        from_id: str,
        to_id: str,
        include_summaries: bool = True,
    ) -> dict:
        """Shortest directed path on CALLS subgraph.

        Args:
            include_summaries: Include summary text on path nodes. Set False for names/paths only.
        """
        try:
            fid = validate_text(from_id, field="from_id", max_length=MAX_ID)
            tid = validate_text(to_id, field="to_id", max_length=MAX_ID)
        except ValueError as exc:
            return err(ErrorCode.VALIDATION_ERROR, str(exc))
        path = await traversal.shortest_path(db, fid, tid)
        if path is None:
            return ok(None)
        if include_summaries:
            return ok(
                [{"id": n.id, "name": n.name, "path": n.path, "summary": n.summary} for n in path]
            )
        return ok([{"id": n.id, "name": n.name, "path": n.path} for n in path])

    @mcp.tool()
    async def graph_stats(include_cohesion: bool = False) -> dict:
        """Node/edge counts broken down by kind.

        Args:
            include_cohesion: Include per-community cohesion scores (expensive, O(edges)).
                              Replaces get_community_cohesion when True.
        """
        stats = await traversal.stats(db)
        if include_cohesion:
            stats["cohesion"] = await get_community_cohesion(db)
        return ok(stats)

    @mcp.tool()
    async def god_nodes(limit: int = 20, include_summaries: bool = True) -> dict:
        """Highest in-degree on CALLS subgraph (most-called functions).

        Args:
            limit: Max nodes to return (1-100). Default 20.
            include_summaries: Include summary text. Set False for names/paths/degree only.
        """
        pairs = await traversal.god_nodes(db, clamp_limit(limit))
        if include_summaries:
            return ok(
                [
                    {
                        "id": n.id,
                        "name": n.name,
                        "path": n.path,
                        "in_degree": deg,
                        "summary": n.summary,
                    }
                    for n, deg in pairs
                ]
            )
        return ok(
            [{"id": n.id, "name": n.name, "path": n.path, "in_degree": deg} for n, deg in pairs]
        )
