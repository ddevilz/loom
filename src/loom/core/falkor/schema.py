from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from loom.config import LOOM_EMBED_DIM

from ..node import NodeKind

if TYPE_CHECKING:
    from .gateway import FalkorGateway

logger = logging.getLogger(__name__)

_SCHEMA_INIT_DONE: set[str] = set()
_SCHEMA_INIT_LOCK = threading.Lock()


def invalidate_schema_init(graph_name: str | None) -> None:
    if isinstance(graph_name, str):
        with _SCHEMA_INIT_LOCK:
            _SCHEMA_INIT_DONE.discard(graph_name)


_ALREADY_EXISTS_FRAGMENTS = (
    "already exists",
    "already indexed",
    "duplicate",
    "index already",
)


def _safe_run(
    gw: FalkorGateway, cypher: str, params: dict[str, Any] | None = None
) -> bool:
    """Run a DDL statement, returning True on success or already-exists, False on unexpected error."""
    try:
        gw.run(cypher, params=params, timeout=5)
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if any(frag in msg for frag in _ALREADY_EXISTS_FRAGMENTS):
            return True
        logger.warning(
            "schema_init DDL failed (continuing): %s | query: %.120s", exc, cypher
        )
        return False


def schema_init(gw, *, embedding_dim: int = LOOM_EMBED_DIM) -> None:
    """Initialize database schema with thread-safe locking.

    Uses double-checked locking pattern with threading.Lock to prevent
    race conditions when multiple threads attempt to initialize the schema
    simultaneously (via asyncio.to_thread calls).
    """
    graph_name = getattr(gw, "graph_name", None)

    # Fast path: check without lock if already initialized
    if isinstance(graph_name, str) and graph_name in _SCHEMA_INIT_DONE:
        return

    # Acquire lock for initialization
    with _SCHEMA_INIT_LOCK:
        # Double-check after acquiring lock (another thread may have initialized)
        if isinstance(graph_name, str) and graph_name in _SCHEMA_INIT_DONE:
            return

        # Run all DDL statements regardless of individual failures (best-effort schema
        # creation). all_ok tracks whether every statement succeeded or was already-exists;
        # the graph is only cached as initialised when the full set passes.
        results = [
            _safe_run(gw, "CREATE INDEX ON :Node(id)"),
            _safe_run(gw, "CREATE INDEX ON :Node(kind)"),
            _safe_run(gw, "CREATE INDEX ON :Node(name)"),
            _safe_run(gw, "CREATE INDEX ON :Node(community_id)"),
            _safe_run(gw, "CREATE INDEX ON :Node(path)"),
        ]

        # per-kind indexes (support fast label-specific lookups like (:Function {id: ...}))
        for kind in NodeKind:
            label = kind.name.title()
            results.append(_safe_run(gw, f"CREATE INDEX ON :`{label}`(id)"))

        # vector index — embedding_dim is an int from config, safe to interpolate
        assert isinstance(embedding_dim, int), "embedding_dim must be int"
        results.append(
            _safe_run(
                gw,
                (
                    "CREATE VECTOR INDEX FOR (n:Node) ON (n.embedding) "
                    f"OPTIONS {{dimension: {embedding_dim}, similarityFunction: 'cosine'}}"
                ),
            )
        )

        all_ok = all(results)

        # Only mark as initialised when all DDL statements succeeded (or were already-exists).
        # A partial schema must not be cached — the next call must retry.
        if all_ok and isinstance(graph_name, str):
            _SCHEMA_INIT_DONE.add(graph_name)
