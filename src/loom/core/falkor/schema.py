from __future__ import annotations

import threading
from typing import Any

from loom.config import LOOM_EMBED_DIM

from ..node_model import NodeKind

_SCHEMA_INIT_DONE: set[str] = set()
_SCHEMA_INIT_LOCK = threading.Lock()


def invalidate_schema_init(graph_name: str | None) -> None:
    if isinstance(graph_name, str):
        _SCHEMA_INIT_DONE.discard(graph_name)


_ALREADY_EXISTS_FRAGMENTS = (
    "already exists",
    "already indexed",
    "duplicate",
    "index already",
)


def _safe_run(gw, cypher: str, params: dict[str, Any] | None = None) -> None:
    try:
        gw.run(cypher, params=params, timeout=5)
    except Exception as exc:
        msg = str(exc).lower()
        if any(frag in msg for frag in _ALREADY_EXISTS_FRAGMENTS):
            return
        import logging

        logging.getLogger(__name__).warning(
            "schema_init DDL failed (continuing): %s | query: %.120s", exc, cypher
        )


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

        # property indexes
        _safe_run(gw, "CREATE INDEX ON :Node(id)")
        _safe_run(gw, "CREATE INDEX ON :Node(kind)")
        _safe_run(gw, "CREATE INDEX ON :Node(name)")
        _safe_run(gw, "CREATE INDEX ON :Node(community_id)")
        _safe_run(gw, "CREATE INDEX ON :Node(path)")

        # per-kind indexes (support fast label-specific lookups like (:Function {id: ...}))
        for kind in NodeKind:
            label = kind.name.title()
            _safe_run(gw, f"CREATE INDEX ON :`{label}`(id)")

        # vector index for similarity search
        _safe_run(
            gw,
            (
                "CREATE VECTOR INDEX FOR (n:Node) ON (n.embedding) "
                f"OPTIONS {{dimension: {embedding_dim}, similarityFunction: 'cosine'}}"
            ),
        )

        if isinstance(graph_name, str):
            _SCHEMA_INIT_DONE.add(graph_name)
