from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from loom.core import Node, NodeKind, NodeSource


@dataclass(frozen=True)
class JiraConfig:
    base_url: str
    email: str
    api_token: str
    project_key: str
    jql: str | None = None
    last_synced_at: str | None = None


def _build_jql(config: JiraConfig) -> str:
    clauses: list[str] = []
    if config.jql:
        clauses.append(f"({config.jql})")
    else:
        clauses.append(f"project = {config.project_key}")
    if config.last_synced_at:
        clauses.append(f'updated >= "{config.last_synced_at}"')
    return " AND ".join(clauses)


def _auth_header(config: JiraConfig) -> str:
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _normalize_issue(issue: dict[str, Any], config: JiraConfig) -> Node:
    fields = issue.get("fields", {})
    key = str(issue.get("key"))
    summary = str(fields.get("summary") or "").strip()
    description = fields.get("description")
    if isinstance(description, dict):
        description_text = json.dumps(description)
    else:
        description_text = str(description or "")
    combined = f"{summary}. {description_text[:500]}".strip().strip(".")

    issuetype = fields.get("issuetype") or {}
    status = fields.get("status") or {}
    reporter = fields.get("reporter") or {}

    return Node(
        id=f"doc:jira:{key}",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=key,
        summary=combined,
        path=f"jira://{config.project_key}/{key}",
        metadata={
            "ticket_type": issuetype.get("name"),
            "status": status.get("name"),
            "epic": fields.get("customfield_epic") or fields.get("epic") or fields.get("epic_key"),
            "labels": fields.get("labels") or [],
            "sprint": fields.get("customfield_sprint") or fields.get("sprint_name") or fields.get("sprint"),
            "reporter": reporter.get("displayName") or reporter.get("emailAddress") or reporter.get("name"),
            "created": fields.get("created"),
            "url": f"{config.base_url.rstrip('/')}/browse/{key}",
        },
    )


def _fetch_search_results(config: JiraConfig) -> list[dict[str, Any]]:
    jql = _build_jql(config)
    url = (
        f"{config.base_url.rstrip('/')}/rest/api/3/search"
        f"?jql={quote(jql)}&maxResults=100&fields=summary,description,issuetype,status,labels,created,reporter,epic,customfield_epic,customfield_sprint,sprint,sprint_name"
    )
    req = Request(
        url,
        headers={
            "Authorization": _auth_header(config),
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(req) as resp:  # nosec - Jira URL is user-configured
        data = json.loads(resp.read().decode("utf-8"))
    issues = data.get("issues") or []
    return [issue for issue in issues if (issue.get("fields") or {}).get("status", {}).get("name") != "Won't Fix"]


async def fetch_jira_nodes(config: JiraConfig) -> list[Node]:
    issues = await asyncio.to_thread(_fetch_search_results, config)
    return [_normalize_issue(issue, config) for issue in issues]
