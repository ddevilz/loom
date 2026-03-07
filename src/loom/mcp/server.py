from __future__ import annotations

from loom.config import LOOM_LLM_MODEL
from loom.core import LoomGraph
from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.drift.detector import detect_ast_drift
from loom.drift.detector import detect_violations
from loom.llm.client import LLMClient
from loom.query.traceability import impact_of_ticket, tickets_for_function, unimplemented_tickets
from loom.search.searcher import search

_CALLS_REL = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)

try:
    from fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None  # type: ignore


def _row_to_code_node(row: dict[str, object]) -> Node | None:
    node_id = row.get("id")
    kind = row.get("kind")
    if not isinstance(node_id, str) or not isinstance(kind, str):
        return None
    try:
        node_kind = NodeKind(kind)
    except Exception:
        return None
    return Node(
        id=node_id,
        kind=node_kind,
        source=NodeSource.CODE,
        name=str(row.get("name") or node_id),
        summary=row.get("summary") if isinstance(row.get("summary"), str) else None,
        path=str(row.get("path") or ""),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


def _row_to_edge(row: dict[str, object]) -> Edge | None:
    from_id = row.get("from_id")
    to_id = row.get("to_id")
    if not isinstance(from_id, str) or not isinstance(to_id, str):
        return None
    return Edge(from_id=from_id, to_id=to_id, kind=EdgeType.LOOM_IMPLEMENTS, metadata={})


def _row_to_doc_node(row: dict[str, object]) -> Node | None:
    node_id = row.get("id")
    if not isinstance(node_id, str):
        return None
    return Node(
        id=node_id,
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=str(row.get("name") or node_id),
        summary=row.get("summary") if isinstance(row.get("summary"), str) else None,
        path=str(row.get("path") or ""),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


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
            f"MATCH (a)-[r:{_CALLS_REL}]->(b {{id: $id}}) RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
            {"id": node_id},
        )
        return rows

    @mcp.tool()
    async def get_spec(node_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await tickets_for_function(node_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def check_drift(node_id: str) -> dict[str, object]:
        graph = LoomGraph(graph_name=graph_name)
        code_rows = await graph.query(
            "MATCH (f {id: $id}) RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata",
            {"id": node_id},
        )
        doc_rows = await graph.query(
            f"MATCH (f {{id: $id}})-[:{_LOOM_IMPL_REL}]->(t) RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"id": node_id},
        )
        edge_rows = await graph.query(
            f"MATCH (f {{id: $id}})-[r:{_LOOM_IMPL_REL}]->(t) RETURN f.id AS from_id, t.id AS to_id",
            {"id": node_id},
        )

        code_nodes = [node for row in code_rows if (node := _row_to_code_node(row)) is not None]
        doc_nodes = [node for row in doc_rows if (node := _row_to_doc_node(row)) is not None]
        implements_edges = [edge for row in edge_rows if (edge := _row_to_edge(row)) is not None]

        ast_drift: list[dict[str, object]] = []
        if code_nodes:
            current_node = code_nodes[0]
            for row in doc_rows:
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                previous_summary = metadata.get("previous_code_summary")
                if not isinstance(previous_summary, str):
                    continue
                previous_node = current_node.model_copy(update={"summary": previous_summary})
                report = detect_ast_drift(previous_node, current_node)
                if report.changed:
                    ast_drift.append({"node_id": report.node_id, "reasons": report.reasons})

        semantic_violations: list[dict[str, object]] = []
        if LOOM_LLM_MODEL and code_nodes and doc_nodes and implements_edges:
            llm = LLMClient(model=LOOM_LLM_MODEL)
            reports = await detect_violations(code_nodes, doc_nodes, implements_edges, llm=llm, model=LOOM_LLM_MODEL)
            semantic_violations = [
                {"code_id": report.code_id, "doc_id": report.doc_id, "confidence": report.confidence, "reason": report.reason}
                for report in reports
            ]

        return {"ast_drift": ast_drift, "semantic_violations": semantic_violations}

    @mcp.tool()
    async def get_impact(ticket_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        rows = await graph.query(
            "MATCH (t) WHERE (t.name = $ticket_id OR t.id = $ticket_id) AND t.path STARTS WITH 'jira://' "
            "RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"ticket_id": ticket_id},
        )
        return rows

    @mcp.tool()
    async def unimplemented() -> list[dict[str, object]]:
        graph = LoomGraph(graph_name=graph_name)
        nodes = await unimplemented_tickets(graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    return mcp
