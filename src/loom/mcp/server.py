from __future__ import annotations

from loom.config import LOOM_LLM_MODEL
from loom.core import LoomGraph
from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_metadata_value, row_to_node
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
    return row_to_node(
        row,
        source=NodeSource.CODE,
        fallback_kind=NodeKind.FUNCTION,
        require_str_id=True,
        require_valid_kind=True,
        summary_must_be_str=True,
    )


def _row_to_edge(row: dict[str, object]) -> Edge | None:
    from_id = row.get("from_id")
    to_id = row.get("to_id")
    if not isinstance(from_id, str) or not isinstance(to_id, str):
        return None
    return Edge(from_id=from_id, to_id=to_id, kind=EdgeType.LOOM_IMPLEMENTS, metadata={})


def _row_to_doc_node(row: dict[str, object]) -> Node | None:
    return row_to_node(
        row,
        source=NodeSource.DOC,
        fallback_kind=NodeKind.SECTION,
        allowed_kinds={NodeKind.DOCUMENT, NodeKind.CHAPTER, NodeKind.SECTION, NodeKind.SUBSECTION, NodeKind.PARAGRAPH},
        require_str_id=True,
        summary_must_be_str=True,
    )


def _row_to_ast_drift(row: dict[str, object]) -> dict[str, object] | None:
    node_id = row.get("node_id")
    if not isinstance(node_id, str):
        return None
    reasons = row.get("reasons")
    if isinstance(reasons, list):
        normalized_reasons = [reason for reason in reasons if isinstance(reason, str)]
    else:
        normalized_reasons = []
    if not normalized_reasons:
        metadata = deserialize_metadata_value(row.get("metadata"))
        if isinstance(metadata, dict):
            metadata_reasons = metadata.get("reasons")
            if isinstance(metadata_reasons, list):
                normalized_reasons = [reason for reason in metadata_reasons if isinstance(reason, str)]
    if not normalized_reasons:
        link_reason = row.get("link_reason")
        if isinstance(link_reason, str) and link_reason:
            normalized_reasons = [part.strip() for part in link_reason.split(";") if part.strip()]
    return {"node_id": node_id, "reasons": normalized_reasons}


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
        drift_rows = await graph.query(
            f"MATCH (f {{id: $id}})-[r:{EdgeTypeAdapter.to_storage(EdgeType.LOOM_VIOLATES)}]->() "
            "WHERE r.link_method = 'ast_diff' "
            "RETURN f.id AS node_id, r.link_reason AS link_reason, r.metadata AS metadata",
            {"id": node_id},
        )

        code_nodes = [node for row in code_rows if (node := _row_to_code_node(row)) is not None]
        doc_nodes = [node for row in doc_rows if (node := _row_to_doc_node(row)) is not None]
        implements_edges = [edge for row in edge_rows if (edge := _row_to_edge(row)) is not None]
        ast_drift = [report for row in drift_rows if (report := _row_to_ast_drift(row)) is not None]

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
