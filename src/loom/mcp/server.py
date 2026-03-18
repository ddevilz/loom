from __future__ import annotations

from loom.core import EdgeType, LoomGraph
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_metadata_value
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.traceability import (
    impact_of_ticket,
    tickets_for_function,
    unimplemented_tickets,
)
from loom.search.searcher import search

_CALLS_REL = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
_VIOLATES_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_VIOLATES)

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore

_MAX_QUERY_LENGTH = 1000
_MAX_IDENTIFIER_LENGTH = 512


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


def _require_non_empty_text(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must be <= {max_length} characters")
    return normalized


def _format_caller_row(row: dict[str, object]) -> dict[str, object] | None:
    node_id = row.get("id")
    name = row.get("name")
    path = row.get("path")
    if (
        not isinstance(node_id, str)
        or not isinstance(name, str)
        or not isinstance(path, str)
    ):
        return None
    confidence = row.get("confidence")
    return {
        "id": node_id,
        "name": name,
        "path": path,
        "confidence": float(confidence)
        if isinstance(confidence, (int, float))
        else 0.0,
    }


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
        """Search for code and documentation nodes using semantic similarity.

        Uses nomic-embed-text vector search combined with name-match fallback.
        Returns nodes ranked by relevance score. Use this to find functions,
        classes, or doc sections related to a concept before calling other tools.

        Args:
            query: Natural-language description of what you're looking for.
            limit: Maximum results to return (1–100, default 10).
        """
        query = _require_non_empty_text(
            query, field_name="query", max_length=_MAX_QUERY_LENGTH
        )
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
        """Return all functions/methods that directly call the given node.

        Traverses one hop of incoming CALLS edges. Each result includes the
        caller's id, name, file path, and confidence score of the edge.
        Use get_blast_radius for the full transitive caller tree.

        Args:
            node_id: The exact node id (e.g. py::src/loom/query/blast_radius.py::build_blast_radius_payload).
        """
        node_id = _require_non_empty_text(
            node_id, field_name="node_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        rows = await graph.query(
            f"MATCH (a)-[r:{_CALLS_REL}]->(b {{id: $id}}) RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
            {"id": node_id},
        )
        return [
            formatted
            for row in rows
            if (formatted := _format_caller_row(row)) is not None
        ]

    @mcp.tool()
    async def get_spec(node_id: str) -> list[dict[str, object]]:
        """Return Jira tickets linked to a code node via LOOM_IMPLEMENTS edges.

        Shows which tickets this function/class is implementing. Useful for
        checking whether a symbol is covered by a spec or requirement.

        Args:
            node_id: The exact node id of the code symbol to look up.
        """
        node_id = _require_non_empty_text(
            node_id, field_name="node_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        nodes = await tickets_for_function(node_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def check_drift(node_id: str) -> dict[str, object]:
        """Check whether a code node has drifted from its linked documentation.

        Returns AST-level drift records from LOOM_VIOLATES edges — cases where
        the indexed snapshot of a function no longer matches the spec it was
        linked to. Returns an empty ast_drift list when there is no recorded drift.

        Args:
            node_id: The exact node id of the code symbol to inspect.
        """
        node_id = _require_non_empty_text(
            node_id, field_name="node_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
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
    async def get_blast_radius(node_id: str, depth: int = 3) -> dict[str, object]:
        """Return nodes that would be affected if node_id changes.

        Walks incoming CALLS edges transitively (callers of callers) so the
        result is the true blast radius: every node that depends on this one.
        Results are ranked by Personalized PageRank on the CALLS subgraph.
        """
        node_id = _require_non_empty_text(
            node_id, field_name="node_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        return await build_blast_radius_payload(
            graph,
            node_id=node_id,
            depth=_clamp_depth(depth),
        )

    @mcp.tool()
    async def get_impact(ticket_id: str) -> list[dict[str, object]]:
        """Return code nodes linked to a Jira ticket via LOOM_IMPLEMENTS edges.

        The inverse of get_spec: given a ticket, returns the functions/classes
        that implement it. Useful for understanding the code impact of a ticket
        or for validating that a ticket is fully implemented.

        Args:
            ticket_id: Jira ticket key (e.g. LOOM-42) or full node id.
        """
        ticket_id = _require_non_empty_text(
            ticket_id, field_name="ticket_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> list[dict[str, object]]:
        """Fetch raw Jira ticket data from the graph by ticket key or node id.

        Returns the ticket's id, name, summary, path, and metadata as stored
        in FalkorDB. Use this to read ticket details (title, description) before
        reasoning about code-to-spec alignment.

        Args:
            ticket_id: Jira ticket key (e.g. LOOM-42) or exact node id.
        """
        ticket_id = _require_non_empty_text(
            ticket_id, field_name="ticket_id", max_length=_MAX_IDENTIFIER_LENGTH
        )
        rows = await graph.query(
            "MATCH (t) WHERE (t.name = $ticket_id OR t.id = $ticket_id) AND t.path STARTS WITH 'jira://' "
            "RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"ticket_id": ticket_id},
        )
        return rows

    @mcp.tool()
    async def unimplemented() -> list[dict[str, object]]:
        """Return Jira tickets that have no linked code nodes (unimplemented tickets).

        A ticket is unimplemented when it has no LOOM_IMPLEMENTS edges pointing
        to it from any code symbol. Useful for finding spec gaps: requirements
        that exist in Jira but are not yet reflected in the codebase.
        """
        nodes = await unimplemented_tickets(graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def relink(
        embedding_threshold: float = 0.75,
        name_threshold: float = 0.6,
    ) -> dict[str, object]:
        """Re-run the semantic linker on all graph nodes without re-indexing.

        Fetches all code nodes and doc nodes already in the graph and re-creates
        LOOM_IMPLEMENTS edges based on embedding similarity and name matching.
        Call this after importing new Jira tickets to link them to existing code,
        or after the graph has been updated incrementally.

        Args:
            embedding_threshold: Minimum cosine similarity to create an IMPLEMENTS edge (default 0.75).
            name_threshold: Minimum name-match score to create an IMPLEMENTS edge (default 0.6).
        """
        from loom.ingest.utils import (
            get_code_nodes_for_linking,
            get_doc_nodes_for_linking,
        )
        from loom.linker.linker import SemanticLinker

        code_nodes = await get_code_nodes_for_linking(graph)
        doc_nodes = await get_doc_nodes_for_linking(graph)

        if not code_nodes or not doc_nodes:
            return {
                "edges_created": 0,
                "code_nodes": len(code_nodes),
                "doc_nodes": len(doc_nodes),
                "message": "Nothing to link — index code and docs first.",
            }

        linker = SemanticLinker(
            embedding_threshold=max(0.0, min(1.0, embedding_threshold)),
            name_threshold=max(0.0, min(1.0, name_threshold)),
        )
        edges = await linker.link(code_nodes, doc_nodes, graph)
        return {
            "edges_created": len(edges),
            "code_nodes": len(code_nodes),
            "doc_nodes": len(doc_nodes),
        }

    return mcp
