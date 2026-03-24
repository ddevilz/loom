from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loom.core import Edge, Node


@dataclass(frozen=True)
class TicketFetchResult:
    """Result of a ticket connector fetch operation."""

    nodes: list[Node]
    edges: list[Edge]  # inter-ticket edges (DEPENDS_ON etc.)
    provider: str


@runtime_checkable
class TicketConnector(Protocol):
    """Protocol for ticket source connectors.

    Implementors: GitHubConnector, JiraConnector, LinearConnector.
    Each connector fetches tickets from its source system and normalizes
    them into Loom Node objects with NodeKind.TICKET / NodeSource.TICKET.
    """

    @property
    def provider_name(self) -> str:
        """Return provider identifier (e.g. 'github', 'jira', 'linear')."""
        ...

    async def fetch(self) -> TicketFetchResult:
        """Fetch all tickets and inter-ticket edges from the source system.

        Returns:
            TicketFetchResult with nodes (ticket Nodes) and edges (DEPENDS_ON etc.)
        """
        ...
