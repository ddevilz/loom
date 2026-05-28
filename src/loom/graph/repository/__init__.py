"""Repository layer — domain-driven data access.

All sub-repositories are composed here into a single Repository facade.
Construction requires a connected DB instance.

Usage:
    db = DB(path)
    db.connect()
    repo = Repository(db)
    node = repo.nodes.get("function:src/auth.py:validate_token")
"""
from __future__ import annotations

from loom.graph.db import DB
from loom.graph.repository.analytics import AnalyticsRepository
from loom.graph.repository.context import ContextRepository
from loom.graph.repository.edges import EdgeRepository
from loom.graph.repository.nodes import NodeRepository
from loom.graph.repository.search import SearchRepository
from loom.graph.repository.sessions import SessionRepository
from loom.graph.repository.traversal import TraversalRepository

__all__ = [
    "Repository",
    "NodeRepository",
    "EdgeRepository",
    "SearchRepository",
    "TraversalRepository",
    "ContextRepository",
    "SessionRepository",
    "AnalyticsRepository",
]


class Repository:
    """Composed repository facade.

    Eagerly constructs all 7 sub-repositories at instantiation time.
    Zero per-request overhead — all state is in the shared DB instance.

    Attributes:
        nodes: Node CRUD and lookup.
        edges: Edge CRUD.
        search: Full-text and LIKE search.
        traversal: Graph traversal (neighbors, blast_radius, etc.).
        context: Context packets and session primer.
        sessions: Session tracking and delta queries.
        analytics: Token-saving analytics.
    """

    __slots__ = ("db", "nodes", "edges", "search", "traversal", "context", "sessions", "analytics")

    def __init__(self, db: DB) -> None:
        self.db = db
        self.nodes = NodeRepository(db)
        self.edges = EdgeRepository(db)
        self.search = SearchRepository(db)
        self.traversal = TraversalRepository(db)
        self.context = ContextRepository(db)
        self.sessions = SessionRepository(db)
        self.analytics = AnalyticsRepository(db)
