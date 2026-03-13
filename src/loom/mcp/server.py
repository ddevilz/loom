from __future__ import annotations

from loom.core import EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_metadata_value, row_to_node
from loom.query.traceability import (
    impact_of_ticket,
    tickets_for_function,
    unimplemented_tickets,
)
from loom.search.searcher import search

_CALLS_REL = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)
_VIOLATES_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_VIOLATES)

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


def _row_to_doc_node(row: dict[str, object]) -> Node | None:
    return row_to_node(
        row,
        source=NodeSource.DOC,
        fallback_kind=NodeKind.SECTION,
        allowed_kinds={
            NodeKind.DOCUMENT,
            NodeKind.CHAPTER,
            NodeKind.SECTION,
            NodeKind.SUBSECTION,
            NodeKind.PARAGRAPH,
        },
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
                normalized_reasons = [
                    reason for reason in metadata_reasons if isinstance(reason, str)
                ]
    if not normalized_reasons:
        link_reason = row.get("link_reason")
        if isinstance(link_reason, str) and link_reason:
            normalized_reasons = [
                part.strip() for part in link_reason.split(";") if part.strip()
            ]
    return {"node_id": node_id, "reasons": normalized_reasons}


def build_server(graph_name: str = "loom", *, graph: LoomGraph | None = None):
    if FastMCP is None:
        raise RuntimeError("fastmcp is not available")

    mcp = FastMCP("loom")
    if graph is None:
        graph = LoomGraph(graph_name=graph_name)

    def _clamp_limit(limit: int) -> int:
        return max(1, min(limit, 100))

    def _clamp_depth(depth: int) -> int:
        return max(1, min(depth, 10))

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> list[dict[str, object]]:
        results = await search(query, graph, limit=_clamp_limit(limit))
        return [
            {
                "id": r.node.id,
                "name": r.node.name,
                "path": r.node.path,
                "score": r.score,
            }
            for r in results
        ]

    @mcp.tool()
    async def get_callers(node_id: str) -> list[dict[str, object]]:
        rows = await graph.query(
            f"MATCH (a)-[r:{_CALLS_REL}]->(b {{id: $id}}) RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
            {"id": node_id},
        )
        return rows

    @mcp.tool()
    async def get_spec(node_id: str) -> list[dict[str, object]]:
        nodes = await tickets_for_function(node_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def check_drift(node_id: str) -> dict[str, object]:
        drift_rows = await graph.query(
            f"MATCH (f {{id: $id}})-[r:{_VIOLATES_REL}]->() "
            "RETURN f.id AS node_id, r.link_method AS link_method, "
            "r.link_reason AS link_reason, r.metadata AS metadata",
            {"id": node_id},
        )
        ast_drift = [
            report
            for row in drift_rows
            if row.get("link_method") == "ast_diff"
            and (report := _row_to_ast_drift(row)) is not None
        ]

        return {"ast_drift": ast_drift}

    @mcp.tool()
    async def get_blast_radius(node_id: str, depth: int = 3) -> list[dict[str, object]]:
        """Return nodes that would be affected if node_id changes.

        Walks incoming CALLS edges transitively (callers of callers) so the
        result is the true blast radius: every node that depends on this one.
        Results are ranked by Personalized PageRank on the CALLS subgraph.
        """
        nodes = await graph.blast_radius(node_id, depth=_clamp_depth(depth))
        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value}
            for n in nodes
        ]

    @mcp.tool()
    async def get_impact(ticket_id: str) -> list[dict[str, object]]:
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> list[dict[str, object]]:
        rows = await graph.query(
            "MATCH (t) WHERE (t.name = $ticket_id OR t.id = $ticket_id) AND t.path STARTS WITH 'jira://' "
            "RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"ticket_id": ticket_id},
        )
        return rows

    @mcp.tool()
    async def unimplemented() -> list[dict[str, object]]:
        nodes = await unimplemented_tickets(graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    return mcp
