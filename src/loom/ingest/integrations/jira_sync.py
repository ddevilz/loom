from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any, Protocol

from loom.core import LoomGraph, EdgeType, Node, NodeKind, NodeSource
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import coerce_row_node_kind, row_to_node
from loom.ingest.integrations.jira import JiraConfig, _fetch_search_results, _normalize_issue
from loom.linker.linker import SemanticLinker

_REOPENED_STATUSES = {"Reopened", "Open"}
_WONT_FIX_STATUS = "Won't Fix"
_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...


def _coerce_code_kind(raw_kind: Any) -> NodeKind:
    return coerce_row_node_kind(
        raw_kind,
        fallback=NodeKind.FUNCTION,
        allowed_kinds={NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS, NodeKind.INTERFACE, NodeKind.ENUM, NodeKind.TYPE, NodeKind.MODULE, NodeKind.FILE},
    ) or NodeKind.FUNCTION


def _row_to_code_node(row: dict[str, Any]) -> Node:
    return row_to_node(
        row,
        source=NodeSource.CODE,
        fallback_kind=_coerce_code_kind(row.get("kind")),
        allow_embedding=True,
    ) or Node(
        id=str(row.get("id")),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=str(row.get("id")),
        path="",
        metadata={},
    )


async def sync_jira_updates(
    graph: _Graph,
    config: JiraConfig,
    *,
    linker: SemanticLinker | None = None,
) -> list[Node]:
    issues_result = await asyncio.to_thread(_fetch_search_results, config)
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
