from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.ingest.git_linker import TICKET_RE, _extract_ticket_ids
from loom.core.edge import EdgeOrigin, EdgeType


# --- TICKET_RE unit tests ---

def test_regex_extracts_standard_jira_key():
    assert _extract_ticket_ids("fix: resolve PROJ-123 auth bug") == ["PROJ-123"]


def test_regex_extracts_multiple_keys():
    ids = _extract_ticket_ids("PROJ-1 and PROJ-2 fixed")
    assert "PROJ-1" in ids
    assert "PROJ-2" in ids


def test_regex_ignores_lowercase():
    assert _extract_ticket_ids("proj-123 not a ticket") == []


def test_regex_no_tickets_returns_empty():
    assert _extract_ticket_ids("fix: update readme") == []


def test_regex_extracts_two_letter_prefix():
    ids = _extract_ticket_ids("See AB-99 for context")
    assert "AB-99" in ids


# --- Zero-match warning test ---

async def test_no_ticket_ids_logs_warning(caplog):
    """Repos with commits that have no ticket IDs return [] and log a warning."""
    mock_commit = MagicMock()
    mock_commit.message = "fix: update readme without ticket"
    mock_commit.hexsha = "abc123"
    mock_commit.author.email = "dev@example.com"
    mock_commit.committed_datetime.isoformat.return_value = "2026-04-17T10:00:00"
    mock_commit.stats.files = {}

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = [mock_commit]

    mock_graph = MagicMock()
    mock_graph.query = AsyncMock(return_value=[])
    mock_graph.bulk_create_edges = AsyncMock()

    with patch("loom.ingest.git_linker.Repo", return_value=mock_repo):
        with caplog.at_level(logging.WARNING, logger="loom.ingest.git_linker"):
            from loom.ingest.git_linker import link_commits_to_tickets
            edges = await link_commits_to_tickets(
                repo_path=Path("/fake/repo"),
                graph=mock_graph,
            )

    assert edges == []
    assert any("no ticket IDs found" in r.message for r in caplog.records)


# --- Happy path ---

async def test_commit_links_to_jira_node():
    """Commit referencing PROJ-42 creates IMPLEMENTS edge to that Jira node."""
    mock_commit = MagicMock()
    mock_commit.message = "feat: PROJ-42 add user login"
    mock_commit.hexsha = "deadbeef"
    mock_commit.author.email = "alice@example.com"
    mock_commit.committed_datetime.isoformat.return_value = "2026-04-17T12:00:00"
    mock_commit.stats.files = {"src/auth.py": {"lines": 10}}

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = [mock_commit]

    async def fake_query(cypher, params=None):
        if "n.path" in cypher or "path" in (params or {}):
            return [{"id": "py::src/auth.py::login", "path": "src/auth.py"}]
        # Jira node lookup
        return [{"id": "doc:jira://PROJ/PROJ-42:root"}]

    mock_graph = MagicMock()
    mock_graph.query = fake_query
    mock_graph.bulk_create_edges = AsyncMock()

    with patch("loom.ingest.git_linker.Repo", return_value=mock_repo):
        from loom.ingest.git_linker import link_commits_to_tickets
        edges = await link_commits_to_tickets(
            repo_path=Path("/fake/repo"),
            graph=mock_graph,
        )

    assert len(edges) >= 1
    edge = edges[0]
    assert edge.kind == EdgeType.LOOM_IMPLEMENTS
    assert edge.origin == EdgeOrigin.GIT_COMMIT
    assert edge.confidence == 1.0
    assert edge.metadata["commit_sha"] == "deadbeef"
    assert edge.link_method == "git_commit"
