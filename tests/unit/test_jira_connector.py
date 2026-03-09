from __future__ import annotations

import pytest

from loom.core import NodeKind
from loom.ingest.integrations.jira import JiraConfig, _build_jql, fetch_jira_nodes


@pytest.mark.asyncio
async def test_fetch_jira_nodes_maps_issue_to_node(monkeypatch) -> None:
    cfg = JiraConfig(
        base_url="https://jira.example.com",
        email="a@b.com",
        api_token="tok",
        project_key="PROJ",
    )

    monkeypatch.setattr(
        "loom.ingest.integrations.jira._fetch_search_results",
        lambda config: [
            {
                "key": "PROJ-1",
                "fields": {
                    "summary": "Fix login",
                    "description": "Session must be invalidated immediately.",
                    "issuetype": {"name": "Bug"},
                    "status": {"name": "Done"},
                    "labels": ["auth"],
                    "created": "2025-01-01",
                    "reporter": {"displayName": "Dev"},
                    "sprint_name": "Sprint 1",
                },
            }
        ],
    )

    nodes = await fetch_jira_nodes(cfg)
    assert len(nodes) == 1
    assert nodes[0].name == "PROJ-1"
    assert nodes[0].kind == NodeKind.DOCUMENT
    assert "Fix login" in (nodes[0].summary or "")
    assert nodes[0].metadata["status"] == "Done"


def test_build_jql_uses_incremental_sync_clause() -> None:
    cfg = JiraConfig(
        base_url="https://jira.example.com",
        email="a@b.com",
        api_token="tok",
        project_key="PROJ",
        last_synced_at="2025-01-02 10:00",
    )
    jql = _build_jql(cfg)
    assert "project = PROJ" in jql
    assert "updated >=" in jql
