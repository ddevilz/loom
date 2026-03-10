from __future__ import annotations

from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_metadata_value, row_to_node
from loom.errors import NodeResolutionError
from loom.query.traceability import (
    impact_of_ticket,
    tickets_for_function,
    unimplemented_tickets,
)
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
    return Edge(
        from_id=from_id, to_id=to_id, kind=EdgeType.LOOM_IMPLEMENTS, metadata={}
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


def build_server(graph_name: str = "loom"):
    if FastMCP is None:
        raise RuntimeError("fastmcp is not available")

    mcp = FastMCP("loom")

    @mcp.tool()
    async def search_code(query: str, limit: int = 10) -> list[dict[str, object]]:
        """Search code semantically using embeddings and graph expansion.

        Args:
            query (str): Natural language search query. Examples:
                - "authentication validation logic"
                - "how to connect to database"
                - "error handling for user input"
                - "payment processing flow"
            limit (int, optional): Maximum number of results to return. Default 10.
                Use smaller values (5-10) for focused searches, larger (20-50) for broad exploration.

        Returns:
            List of dicts with keys:
                - id (str): Full node ID (e.g., "function:auth/validator.py:validate_user")
                - name (str): Simple node name (e.g., "validate_user")
                - path (str): File path (e.g., "auth/validator.py")
                - score (float): Semantic similarity score (0.0-1.0, higher is better)

        Example usage:
            search_code("user authentication validation", limit=5)
            search_code("database connection setup")
        """
        graph = LoomGraph(graph_name=graph_name)
        results = await search(query, graph, limit=limit)
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
        """Find all functions that call a specific node.

        Args:
            node_id (str): Node ID to find callers for. Can be:
                - Full ID: "function:auth/validator.py:validate_user"
                - Simple name: "validate_user" (will be resolved automatically)
                - Function name from any file

        Returns:
            List of dicts with keys:
                - id (str): Full caller node ID
                - name (str): Caller function name
                - path (str): File path of caller
                - confidence (float): Call relationship confidence (0.0-1.0)

        Example usage:
            get_callers("function:auth/validator.py:validate_user")
            get_callers("validate_user")  # Will resolve automatically
        """
        graph = LoomGraph(graph_name=graph_name)

        # Validate full ID format
        if ":" not in node_id:
            return [
                {
                    "error": f"node_id must be a full ID (e.g., 'function:auth.py:validate'). Got: '{node_id}'",
                    "node_id": node_id,
                }
            ]

        rows = await graph.query(
            f"MATCH (a)-[r:{_CALLS_REL}]->(b {{id: $id}}) RETURN a.id AS id, a.name AS name, a.path AS path, r.confidence AS confidence",
            {"id": node_id},
        )
        return rows

    @mcp.tool()
    async def get_spec(node_id: str) -> list[dict[str, object]]:
        """Get specification or documentation linked to a code node.

        Args:
            node_id (str): Node ID to find specifications for. Can be:
                - Full ID: "function:auth/validator.py:validate_user"
                - Simple name: "validate_user" (will be resolved automatically)

        Returns:
            List of dicts with keys:
                - id (str): Full specification node ID
                - name (str): Specification name (e.g., "User Validation Requirements")
                - path (str): Document path (e.g., "specs/auth.md")

        Note:
            Returns empty list if no specifications are linked to this code.
            Specifications can be from Jira tickets, documentation files, or requirements.

        Example usage:
            get_spec("function:auth/validator.py:validate_user")
            get_spec("validate_user")
        """
        graph = LoomGraph(graph_name=graph_name)

        # Validate full ID format
        if ":" not in node_id:
            return [
                {
                    "error": f"node_id must be a full ID (e.g., 'function:auth.py:validate'). Got: '{node_id}'",
                    "node_id": node_id,
                }
            ]

        nodes = await tickets_for_function(node_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def check_drift(node_id: str) -> dict[str, object]:
        """Check for AST drift and semantic violations between code and specifications.

        Args:
            node_id (str): Node ID to check drift for. Can be:
                - Full ID: "function:auth/validator.py:validate_user"
                - Simple name: "validate_user" (will be resolved automatically)

        Returns:
            Dict with keys:
                - ast_drift (list): List of dicts with AST-level changes:
                    - node_id (str): Affected node ID
                    - reasons (list[str]): Specific change descriptions like:
                        - "signature_changed: (username) -> (username, email)"
                        - "added_parameters: ['email']"
                        - "return_type_changed: bool -> str"
                        - "removed_parameters: ['old_param']"
                - semantic_violations (list): List of dicts with semantic mismatches:
                    - node_id (str): Affected node ID
                    - reasons (list[str]): Semantic violation descriptions
                - error (str, optional): Error message if node resolution failed

        Note:
            - AST drift detects structural changes (signatures, parameters, return types)
            - Semantic violations detect logic/behavior mismatches with specifications
            - Empty lists indicate no detected issues

        Example usage:
            check_drift("function:auth/validator.py:validate_user")
            check_drift("validate_user")
        """
        graph = LoomGraph(graph_name=graph_name)

        # Validate full ID format
        if ":" not in node_id:
            return {
                "ast_drift": [],
                "semantic_violations": [],
                "error": f"node_id must be a full ID (e.g., 'function:auth.py:validate'). Got: '{node_id}'",
                "node_id": node_id,
            }

        _violates_rel = EdgeTypeAdapter.to_storage(EdgeType.LOOM_VIOLATES)
        drift_rows = await graph.query(
            f"MATCH (f {{id: $id}})-[r:{_violates_rel}]->() "
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
        semantic_violations = [
            report
            for row in drift_rows
            if row.get("link_method") != "ast_diff"
            and (report := _row_to_ast_drift(row)) is not None
        ]

        return {"ast_drift": ast_drift, "semantic_violations": semantic_violations}

    @mcp.tool()
    async def get_blast_radius(node_id: str, depth: int = 3) -> list[dict[str, object]]:
        """Return nodes that would be affected if node_id changes (impact analysis).

        Walks incoming CALLS edges transitively (callers of callers) so the
        result is the true blast radius: every node that depends on this one.
        Results are ranked by Personalized PageRank on the CALLS subgraph.

        Args:
            node_id (str): Node ID to analyze. Can be:
                - Full ID: "function:auth/validator.py:validate_user"
                - Simple name: "validate_user" (will be resolved automatically)
            depth (int, optional): How deep to traverse the call graph. Default 3.
                - 1: Direct callers only
                - 2-3: Typical impact radius (recommended)
                - 4-5: Deep impact analysis (may be slow)

        Returns:
            List of dicts with keys:
                - id (str): Full affected node ID
                - name (str): Node name
                - path (str): File path
                - kind (str): Node kind ("function", "class", "method", etc.)
                - error (str, optional): Error message if node resolution failed

        Note:
            Results are sorted by impact priority - nodes that would be most
            affected appear first. This helps prioritize testing and review.

        Example usage:
            get_blast_radius("function:auth/validator.py:validate_user", depth=3)
            get_blast_radius("validate_user", depth=2)  # Shallow analysis
        """
        graph = LoomGraph(graph_name=graph_name)

        # Validate full ID format
        if ":" not in node_id:
            return [
                {
                    "error": f"node_id must be a full ID (e.g., 'function:auth.py:validate'). Got: '{node_id}'",
                    "node_id": node_id,
                }
            ]

        try:
            nodes = await graph.blast_radius(node_id, depth=depth)
        except NodeResolutionError as e:
            return [{"error": str(e), "node_id": node_id}]

        return [
            {"id": n.id, "name": n.name, "path": n.path, "kind": n.kind.value}
            for n in nodes
        ]

    @mcp.tool()
    async def get_impact(ticket_id: str) -> list[dict[str, object]]:
        """Get code nodes impacted by a ticket or requirement.

        Args:
            ticket_id (str): Ticket ID to analyze. Can be:
                - Jira ticket: "PROJ-123", "AUTH-456"
                - Full ticket ID: "jira://your-domain.atlassian.net/browse/PROJ-123"
                - Requirement name from documentation

        Returns:
            List of dicts with keys:
                - id (str): Full affected code node ID
                - name (str): Code node name
                - path (str): File path

        Note:
            This shows which code implements or is related to the ticket.
            Useful for understanding what needs to be modified or tested
            when working on a specific requirement.

        Example usage:
            get_impact("PROJ-123")
            get_impact("AUTH-456")
        """
        graph = LoomGraph(graph_name=graph_name)
        nodes = await impact_of_ticket(ticket_id, graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    @mcp.tool()
    async def get_ticket(ticket_id: str) -> list[dict[str, object]]:
        """Retrieve ticket details from Jira integration.

        Args:
            ticket_id (str): Ticket ID to retrieve. Can be:
                - Jira ticket: "PROJ-123", "AUTH-456"
                - Full ticket ID: "jira://your-domain.atlassian.net/browse/PROJ-123"

        Returns:
            List of dicts with keys:
                - id (str): Full ticket ID
                - name (str): Ticket name/key (e.g., "PROJ-123")
                - summary (str): Ticket title/description
                - path (str): Full Jira URL
                - metadata (dict): Additional ticket data including:
                    - status (str): Ticket status ("In Progress", "Done", etc.)
                    - assignee (str): Assigned person
                    - priority (str): Ticket priority
                    - project (str): Project key

        Note:
            Requires Jira integration to be configured in Loom.
            Returns empty list if ticket not found or Jira not configured.

        Example usage:
            get_ticket("PROJ-123")
            get_ticket("AUTH-456")
        """
        graph = LoomGraph(graph_name=graph_name)
        rows = await graph.query(
            "MATCH (t) WHERE (t.name = $ticket_id OR t.id = $ticket_id) AND t.path STARTS WITH 'jira://' "
            "RETURN t.id AS id, t.name AS name, t.summary AS summary, t.path AS path, t.metadata AS metadata",
            {"ticket_id": ticket_id},
        )
        return rows

    @mcp.tool()
    async def unimplemented() -> list[dict[str, object]]:
        """Find tickets that have no implementation links in the codebase.

        Args:
            None (takes no parameters)

        Returns:
            List of dicts with keys:
                - id (str): Full ticket ID
                - name (str): Ticket name/key (e.g., "PROJ-123")
                - path (str): Jira URL or document path

        Note:
            These are requirements/tickets that exist in the system but
            have no corresponding code implementation. This helps identify
            gaps between requirements and actual implementation.

            Useful for:
            - Planning development work
            - Identifying missing features
            - Ensuring all requirements are implemented

        Example usage:
            unimplemented()  # Get all unimplemented tickets
        """
        graph = LoomGraph(graph_name=graph_name)
        nodes = await unimplemented_tickets(graph)
        return [{"id": n.id, "name": n.name, "path": n.path} for n in nodes]

    return mcp
