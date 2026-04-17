from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from git import InvalidGitRepositoryError, Repo

from loom.core.edge import Edge, EdgeOrigin, EdgeType
from loom.core.types import QueryGraph

logger = logging.getLogger(__name__)

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def _extract_ticket_ids(message: str) -> list[str]:
    """Extract all Jira-style ticket IDs from a commit message."""
    return TICKET_RE.findall(message)


async def link_commits_to_tickets(
    repo_path: Path,
    graph: QueryGraph,
    *,
    since_sha: str | None = None,
) -> list[Edge]:
    """Walk git log and create IMPLEMENTS edges: code nodes → Jira ticket nodes.

    For each commit:
      1. Extract ticket IDs from commit message via TICKET_RE.
      2. Get changed files from the diff.
      3. Resolve changed files → code nodes already in the graph.
      4. For each (code node, ticket ID) pair, look up the Jira node in the graph.
      5. Create LOOM_IMPLEMENTS edge with origin=GIT_COMMIT, confidence=1.0.

    Returns [] (not an error) when no ticket IDs are found in the walked range.
    Logs a WARNING when the entire range has zero ticket references.

    Args:
        repo_path: Root of the git repository.
        graph: Graph instance for queries.
        since_sha: If provided, only walk commits since this SHA (exclusive).
    """
    try:
        repo = Repo(str(repo_path))
    except InvalidGitRepositoryError:
        logger.warning(
            "git_linker: %s is not a valid git repository — skipping git-based linking",
            repo_path,
        )
        return []

    kwargs: dict[str, Any] = {}
    if since_sha:
        kwargs["rev"] = f"{since_sha}..HEAD"

    edges: list[Edge] = []
    any_ticket_found = False

    for commit in repo.iter_commits(**kwargs):
        ticket_ids = _extract_ticket_ids(commit.message or "")
        if not ticket_ids:
            continue

        any_ticket_found = True
        changed_files = list(commit.stats.files.keys())

        for file_path in changed_files:
            # Resolve file path → code nodes in graph (exclude file nodes themselves)
            node_rows = await graph.query(
                "MATCH (n:Node) WHERE n.path = $path AND n.kind <> 'file' "
                "RETURN n.id AS id",
                {"path": file_path},
            )

            for ticket_id in ticket_ids:
                # Look up the Jira ticket node by path prefix
                jira_rows = await graph.query(
                    "MATCH (t:Node) WHERE t.id STARTS WITH $prefix RETURN t.id AS id",
                    {"prefix": "doc:jira://"},
                )
                # Filter to this specific ticket
                matching = [
                    r for r in jira_rows if ticket_id in str(r.get("id", ""))
                ]
                if not matching:
                    continue

                jira_node_id = str(matching[0]["id"])
                raw_msg = commit.message or ""
                str_msg = raw_msg.decode() if isinstance(raw_msg, bytes) else str(raw_msg)
                commit_msg_first_line = str_msg.splitlines()[0][:80]

                hexsha = (
                    commit.hexsha.decode()
                    if isinstance(commit.hexsha, bytes)
                    else str(commit.hexsha)
                )
                for node_row in node_rows:
                    code_node_id = str(node_row["id"])
                    edges.append(
                        Edge(
                            from_id=code_node_id,
                            to_id=jira_node_id,
                            kind=EdgeType.LOOM_IMPLEMENTS,
                            origin=EdgeOrigin.GIT_COMMIT,
                            confidence=1.0,
                            link_method="git_commit",
                            link_reason=(
                                f"commit {hexsha[:8]}: {commit_msg_first_line}"
                            ),
                            metadata={
                                "commit_sha": hexsha,
                                "author": commit.author.email,
                                "timestamp": commit.committed_datetime.isoformat(),
                            },
                        )
                    )

    if not any_ticket_found:
        logger.warning(
            "git_linker: no ticket IDs found in commit range for repo %s — "
            "ensure commit messages reference Jira keys (e.g. PROJ-123). "
            "Git-based Jira linking will produce no edges.",
            repo_path,
        )

    return edges
