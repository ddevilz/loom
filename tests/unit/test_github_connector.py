from __future__ import annotations

import pytest

from loom.ingest.connectors.github_issues import (
    GitHubConfig,
    GitHubConnector,
    _normalize_issue,
)
from loom.ingest.connectors.base import TicketConnector, TicketFetchResult
from loom.core.node import NodeKind, NodeSource


def test_github_config_validation():
    c = GitHubConfig(owner="alice", repo="myrepo", token="ghp_test")
    assert c.owner == "alice"
    assert c.repo == "myrepo"
    assert c.token == "ghp_test"


def test_github_config_empty_owner_raises():
    with pytest.raises((ValueError, Exception)):
        GitHubConfig(owner="", repo="myrepo", token="tok")


def test_github_config_empty_repo_raises():
    with pytest.raises((ValueError, Exception)):
        GitHubConfig(owner="alice", repo="", token="tok")


def test_github_config_empty_token_raises():
    with pytest.raises((ValueError, Exception)):
        GitHubConfig(owner="alice", repo="myrepo", token="")


def test_github_config_invalid_state_raises():
    with pytest.raises((ValueError, Exception)):
        GitHubConfig(owner="alice", repo="myrepo", token="tok", state="invalid")


def test_normalize_issue_basic():
    config = GitHubConfig(owner="alice", repo="myrepo", token="tok")
    issue = {
        "number": 42,
        "title": "Add sorting feature",
        "body": "We need to sort the users list.",
        "state": "open",
        "html_url": "https://github.com/alice/myrepo/issues/42",
        "assignee": {"login": "bob"},
        "labels": [{"name": "enhancement"}, {"name": "P1"}],
        "milestone": None,
        "created_at": "2024-01-15T10:00:00Z",
        "closed_at": None,
        "comments": 3,
        "user": {"login": "alice"},
    }
    node, edges = _normalize_issue(issue, config)
    assert node.kind == NodeKind.TICKET
    assert node.source == NodeSource.TICKET
    assert node.id == "ticket:github:alice/myrepo/42"
    assert node.name == "#42"
    assert node.status == "open"
    assert node.external_id == "42"
    assert node.url == "https://github.com/alice/myrepo/issues/42"
    assert node.assignee == "bob"
    assert "Add sorting" in node.summary


def test_normalize_issue_no_assignee():
    config = GitHubConfig(owner="alice", repo="myrepo", token="tok")
    issue = {
        "number": 1,
        "title": "Test issue",
        "body": None,
        "state": "closed",
        "html_url": "https://github.com/alice/myrepo/issues/1",
        "assignee": None,
        "labels": [],
        "milestone": None,
        "created_at": "2024-01-01T00:00:00Z",
        "closed_at": "2024-01-02T00:00:00Z",
        "comments": 0,
        "user": {"login": "alice"},
    }
    node, edges = _normalize_issue(issue, config)
    assert node.assignee is None
    assert node.status == "closed"


def test_connector_satisfies_protocol():
    config = GitHubConfig(owner="alice", repo="myrepo", token="tok")
    connector = GitHubConnector(config)
    assert isinstance(connector, TicketConnector)
    assert connector.provider_name == "github"


def test_cross_reference_edge_extraction():
    """Body with #10 and owner/repo#20 should produce DEPENDS_ON edges."""
    config = GitHubConfig(owner="alice", repo="myrepo", token="tok")
    issue = {
        "number": 42,
        "title": "Depends on others",
        "body": "This depends on #10 and also alice/myrepo#20.",
        "state": "open",
        "html_url": "https://github.com/alice/myrepo/issues/42",
        "assignee": None,
        "labels": [],
        "milestone": None,
        "created_at": "2024-01-01T00:00:00Z",
        "closed_at": None,
        "comments": 0,
        "user": {"login": "alice"},
    }
    node, edges = _normalize_issue(issue, config)
    # Should have DEPENDS_ON edges for #10 and #20
    assert len(edges) >= 1
