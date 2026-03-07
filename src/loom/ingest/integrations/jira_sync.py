from __future__ import annotations

from inspect import isawaitable
from typing import Any, Protocol

from loom.core import LoomGraph, EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.ingest.integrations.jira import JiraConfig, _fetch_search_results, _normalize_issue
from loom.linker.linker import SemanticLinker

_REOPENED_STATUSES = {"Reopened", "Open"}
_WONT_FIX_STATUS = "Won't Fix"
_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...


def _row_to_code_node(row: dict[str, Any]) -> Node:
    return Node(
        id=str(row.get("id")),
        kind=NodeKind(str(row.get("kind") or NodeKind.FUNCTION.value)),
        source=NodeSource.CODE,
        name=str(row.get("name")),
        summary=row.get("summary"),
        path=str(row.get("path")),
        embedding=row.get("embedding") if isinstance(row.get("embedding"), list) else None,
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


async def sync_jira_updates(
    graph: _Graph,
    config: JiraConfig,
    *,
    linker: SemanticLinker | None = None,
) -> list[Node]:
    issues_result = _fetch_search_results(config)
    issues = await issues_result if isawaitable(issues_result) else issues_result

    updated_nodes: list[Node] = []
    for issue in issues:
        fields = issue.get("fields") or {}
        key = str(issue.get("key"))
        status = (fields.get("status") or {}).get("name")
        ticket_id = f"doc:jira:{key}"

        if status == _WONT_FIX_STATUS:
            await graph.query(
                f"MATCH ()-[r:{_LOOM_IMPL_REL}]->(t {{id: $ticket_id}}) SET r.stale = true, r.stale_reason = 'ticket_wont_fix'",
                {"ticket_id": ticket_id},
            )
            continue

        node = _normalize_issue(issue, config)
        updated_nodes.append(node)
        await graph.bulk_create_nodes([node])

        if status in _REOPENED_STATUSES:
            await graph.query(
                f"MATCH ()-[r:{_LOOM_IMPL_REL}]->(t {{id: $ticket_id}}) SET r.needs_review = true, r.review_reason = 'ticket_reopened'",
                {"ticket_id": ticket_id},
            )

        if linker is not None:
            rows = await graph.query(
                f"MATCH (f)-[:{_LOOM_IMPL_REL}]->(t {{id: $ticket_id}}) RETURN f.id AS id, f.kind AS kind, f.name AS name, f.summary AS summary, f.path AS path, f.metadata AS metadata, f.embedding AS embedding",
                {"ticket_id": ticket_id},
            )
            code_nodes = [_row_to_code_node(row) for row in rows]
            if code_nodes:
                await linker.link(code_nodes, [node], graph)

    return updated_nodes
