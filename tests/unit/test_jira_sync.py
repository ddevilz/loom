from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from loom.core import Node, NodeKind, NodeSource
from loom.ingest.integrations.jira import JiraConfig
from loom.ingest.integrations.jira_sync import sync_jira_updates


@dataclass
class _FakeGraph:
    nodes: list[Node] = field(default_factory=list)
    queries: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    async def query(self, cypher: str, params: dict[str, Any] | None = None):
        self.queries.append((cypher, params))
        if "RETURN f.id AS id" in cypher:
            return []
        return []

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        self.nodes.extend(nodes)


@pytest.mark.asyncio
async def test_sync_jira_updates_upserts_updated_nodes(monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.ingest.integrations.jira_sync._fetch_search_results",
        lambda cfg: [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Fix auth",
                    "description": "Updated description",
                    "status": {"name": "Done"},
                    "issuetype": {"name": "Bug"},
                },
            }
        ],
    )
    graph = _FakeGraph()
    nodes = await sync_jira_updates(
        graph,
        JiraConfig(base_url="https://jira.example.com", email="a@b.com", api_token="tok", project_key="PROJ", last_synced_at="2025-01-01"),
    )
    assert nodes
    assert any(n.name == "PROJ-1" for n in graph.nodes)


@pytest.mark.asyncio
async def test_sync_jira_updates_marks_reopened_for_review(monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.ingest.integrations.jira_sync._fetch_search_results",
        lambda cfg: [
            {
                "key": "PROJ-2",
                "fields": {
                    "summary": "Fix auth",
                    "description": "Updated description",
                    "status": {"name": "Reopened"},
                    "issuetype": {"name": "Bug"},
                },
            }
        ],
    )
    graph = _FakeGraph()
    await sync_jira_updates(
        graph,
        JiraConfig(base_url="https://jira.example.com", email="a@b.com", api_token="tok", project_key="PROJ", last_synced_at="2025-01-01"),
    )
    assert any("needs_review" in q[0] for q in graph.queries)
