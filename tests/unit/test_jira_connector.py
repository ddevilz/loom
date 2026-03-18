from __future__ import annotations

import json

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


def test_fetch_search_results_paginates(monkeypatch) -> None:
    from loom.ingest.integrations.jira import _fetch_search_results

    cfg = JiraConfig(
        base_url="https://jira.example.com",
        email="a@b.com",
        api_token="tok",
        project_key="PROJ",
    )

    responses = [
        # _validate_credentials hits /rest/api/3/myself first
        {"accountId": "user-1", "displayName": "Test User"},
        {
            "issues": [{"key": "PROJ-1", "fields": {"status": {"name": "Done"}}}],
            "total": 2,
            "nextPageToken": "page-2",
        },
        {
            "issues": [{"key": "PROJ-2", "fields": {"status": {"name": "Done"}}}],
            "total": 2,
        },
    ]

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _urlopen(req, timeout=30):
        return _Resp(responses.pop(0))

    monkeypatch.setattr("loom.ingest.integrations.jira.urlopen", _urlopen)

    issues = _fetch_search_results(cfg)

    assert [issue["key"] for issue in issues] == ["PROJ-1", "PROJ-2"]
