from __future__ import annotations

from loom.core import LoomGraph
from loom.drift.detector import detect_violations
from loom.query.traceability import impact_of_ticket, tickets_for_function, unimplemented_tickets
from loom.search.searcher import search

try:
    from fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None  # type: ignore


def build_server(graph_name: str = "loom"):
    if FastMCP is None:
        raise RuntimeError("fastmcp is not available")

    mcp = FastMCP("loom")

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        results = await search(query, graph, limit=limit)
        return [{"id": r.node.id, "name": r.node.name, "path": r.node.path, "score": r.score} for r in results]

    @mcp.tool()
    async def get_callers(node_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        rows = await graph.query(
            "MATCH (a)-[r:CALLS]->(b {id: $id}) RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
            {"id": node_id},
        )
        return rows

    @mcp.tool()
    async def get_spec(node_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await tickets_for_function(node_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def check_drift(node_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        code_rows = await graph.query(
            "MATCH (f {id: $id}) RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata",
            {"id": node_id},
        )
        doc_rows = await graph.query(
            "MATCH (f {id: $id})-[:LOOM_IMPLEMENTS]->(t) RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"id": node_id},
        )
        edge_rows = await graph.query(
            "MATCH (f {id: $id})-[r:LOOM_IMPLEMENTS]->(t) RETURN f.id AS from_id, t.id AS to_id",
            {"id": node_id},
        )
        return [{"code": code_rows, "docs": doc_rows, "edges": edge_rows}]

    @mcp.tool()
    async def get_impact(ticket_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def unimplemented() -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await unimplemented_tickets(graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    return mcp
