from __future__ import annotations

from typing import Any

from ..node import NodeKind

_SCHEMA_INIT_DONE: set[str] = set()


def _safe_run(gw, cypher: str, params: dict[str, Any] | None = None) -> None:
    try:
        gw.run(cypher, params=params, timeout=5)
    except Exception:
        # FalkorDB versions differ on index DDL idempotency support.
        # If an index already exists, CREATE INDEX often errors; we treat that as success.
        return


def schema_init(gw, *, embedding_dim: int = 768) -> None:
    graph_name = getattr(gw, "graph_name", None)
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
            "CREATE VECTOR INDEX FOR (n:Node) ON n.embedding "
            f"OPTIONS {{dimension: {embedding_dim}, similarityFunction: cosine}}"
        ),
    )

    if isinstance(graph_name, str):
        _SCHEMA_INIT_DONE.add(graph_name)
