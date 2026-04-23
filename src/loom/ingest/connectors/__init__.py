"""Ticket source connectors for Loom."""
from loom.ingest.connectors.base import TicketConnector, TicketFetchResult
from loom.ingest.connectors.github_issues import GitHubConfig, GitHubConnector

__all__ = ["GitHubConfig", "GitHubConnector", "TicketConnector", "TicketFetchResult"]
