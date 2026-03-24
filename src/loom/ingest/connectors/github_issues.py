from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tqdm import tqdm

from loom.core import Node, NodeKind, NodeSource
from loom.core.edge import Edge, EdgeType
from loom.ingest.connectors.base import TicketFetchResult

_VALID_STATES = frozenset({"open", "closed", "all"})

# Matches: #123  or  owner/repo#123
_CROSS_REF_RE = re.compile(r"(?:[\w.-]+/[\w.-]+)?#(\d+)")


@dataclass(frozen=True)
class GitHubConfig:
    """Configuration for the GitHub Issues connector."""

    owner: str
    repo: str
    token: str
    state: str = "all"
    labels_filter: list[str] | None = None
    last_synced_at: str | None = None

    def __post_init__(self) -> None:
        if not self.owner:
            raise ValueError("GitHub owner cannot be empty")
        if not self.repo:
            raise ValueError("GitHub repo cannot be empty")
        if not self.token:
            raise ValueError("GitHub token cannot be empty")
        if self.state not in _VALID_STATES:
            raise ValueError(
                f"GitHub state must be one of {sorted(_VALID_STATES)}, got: {self.state!r}"
            )


class GitHubConnector:
    """Connector that fetches GitHub Issues and normalizes them into Loom Nodes.

    Implements the TicketConnector protocol.
    """

    def __init__(self, config: GitHubConfig) -> None:
        self._config = config

    @property
    def provider_name(self) -> str:
        """Return provider identifier."""
        return "github"

    async def fetch(self) -> TicketFetchResult:
        """Fetch all issues and inter-ticket edges from GitHub."""
        raw_issues = await asyncio.to_thread(_fetch_issues_sync, self._config)
        nodes: list[Node] = []
        edges: list[Edge] = []
        for issue in raw_issues:
            node, issue_edges = _normalize_issue(issue, self._config)
            nodes.append(node)
            edges.extend(issue_edges)
        return TicketFetchResult(nodes=nodes, edges=edges, provider=self.provider_name)


def _build_url(config: GitHubConfig, page: int) -> str:
    params: dict[str, Any] = {
        "state": config.state,
        "per_page": 100,
        "page": page,
    }
    if config.labels_filter:
        params["labels"] = ",".join(config.labels_filter)
    if config.last_synced_at:
        params["since"] = config.last_synced_at
    base = f"https://api.github.com/repos/{config.owner}/{config.repo}/issues"
    return f"{base}?{urlencode(params)}"


def _make_request(url: str, token: str) -> Request:
    return Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )


def _parse_next_link(link_header: str) -> str | None:
    """Extract the URL for rel="next" from a GitHub Link header."""
    match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    return match.group(1) if match else None


def _fetch_issues_sync(config: GitHubConfig) -> list[dict[str, Any]]:
    """Synchronous implementation — runs in a thread via asyncio.to_thread."""
    all_issues: list[dict[str, Any]] = []
    next_url: str | None = _build_url(config, page=1)

    show_progress = os.environ.get("LOOM_PROGRESS", "1") != "0" and os.isatty(1)
    with tqdm(
        desc="github issues", unit="issue", disable=not show_progress
    ) as progress:
        while next_url:
            req = _make_request(next_url, config.token)
            sleep_secs = 0
            try:
                with urlopen(req, timeout=30) as resp:  # nosec B310
                    # Handle rate limiting
                    remaining = resp.headers.get("X-RateLimit-Remaining")
                    reset_ts = resp.headers.get("X-RateLimit-Reset")
                    if remaining is not None and int(remaining) == 0 and reset_ts:
                        sleep_secs = max(0, int(reset_ts) - int(time.time())) + 1

                    body = resp.read().decode("utf-8")
                    link_header = resp.headers.get("Link") or ""

                data: list[dict[str, Any]] = json.loads(body)
            except HTTPError as exc:
                if exc.code == 401:
                    raise ValueError(
                        f"GitHub authentication failed (HTTP 401): "
                        f"verify token for {config.owner}/{config.repo}"
                    ) from exc
                if exc.code == 403:
                    raise ValueError(
                        f"GitHub access forbidden (HTTP 403): "
                        f"check token permissions for {config.owner}/{config.repo}"
                    ) from exc
                raise

            # Filter out pull requests — they appear in issues endpoint
            issues_only = [item for item in data if "pull_request" not in item]

            # Filter out "not_planned" closed issues
            issues_only = [
                item
                for item in issues_only
                if not (
                    item.get("state") == "closed"
                    and item.get("state_reason") == "not_planned"
                )
            ]

            all_issues.extend(issues_only)
            progress.update(len(issues_only))
            progress.refresh()

            next_url = _parse_next_link(link_header) if link_header else None

            # Stop paginating if the page returned fewer items than requested
            if len(data) < 100:
                next_url = None

            if sleep_secs > 0 and next_url:
                time.sleep(sleep_secs)

    return all_issues


def _normalize_issue(
    issue: dict[str, Any], config: GitHubConfig
) -> tuple[Node, list[Edge]]:
    """Normalize a raw GitHub issue dict into a Loom Node and any DEPENDS_ON edges."""
    number = issue["number"]
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    summary = f"{title}. {body[:500]}".strip().strip(".")

    assignee_obj = issue.get("assignee")
    assignee = assignee_obj.get("login") if assignee_obj else None

    labels = [lbl["name"] for lbl in (issue.get("labels") or [])]
    milestone_obj = issue.get("milestone")
    milestone = milestone_obj.get("title") if milestone_obj else None
    author_obj = issue.get("user") or {}
    author = author_obj.get("login")

    node_id = Node.make_ticket_id(
        "github", f"{config.owner}/{config.repo}", str(number)
    )

    node = Node(
        id=node_id,
        kind=NodeKind.TICKET,
        source=NodeSource.TICKET,
        name=f"#{number}",
        path=f"github://{config.owner}/{config.repo}/{number}",
        summary=summary,
        status=issue.get("state"),
        priority=None,
        assignee=assignee,
        url=issue.get("html_url"),
        external_id=str(number),
        metadata={
            "labels": labels,
            "milestone": milestone,
            "created_at": issue.get("created_at"),
            "closed_at": issue.get("closed_at"),
            "comments": issue.get("comments", 0),
            "author": author,
        },
    )

    # Extract cross-references from the issue body to build DEPENDS_ON edges
    edges: list[Edge] = []
    seen_refs: set[str] = set()
    if body:
        for match in _CROSS_REF_RE.finditer(body):
            ref_number = match.group(1)
            if ref_number == str(number):
                continue  # skip self-reference
            if ref_number in seen_refs:
                continue
            seen_refs.add(ref_number)
            ref_id = Node.make_ticket_id(
                "github", f"{config.owner}/{config.repo}", ref_number
            )
            edges.append(
                Edge(
                    from_id=node_id,
                    to_id=ref_id,
                    kind=EdgeType.DEPENDS_ON,
                )
            )

    return node, edges


async def fetch_github_nodes(config: GitHubConfig) -> list[Node]:
    """Convenience function — fetch GitHub issues and return only the Node list.

    Provided for backward compatibility with the existing pipeline pattern
    (mirrors fetch_jira_nodes in loom.ingest.integrations.jira).
    """
    connector = GitHubConnector(config)
    result = await connector.fetch()
    return result.nodes
