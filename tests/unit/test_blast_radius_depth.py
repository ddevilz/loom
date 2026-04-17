"""Tests for blast_radius depth cap and config-based max depth enforcement."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.query.blast_radius import build_blast_radius_payload


async def test_blast_radius_respects_depth() -> None:
    """depth argument is forwarded to graph.blast_radius, not silently dropped."""
    graph = MagicMock()
    graph.query = AsyncMock(
        side_effect=[
            [{"id": "a", "name": "fn_a", "path": "x.py", "kind": "function"}],
            [],  # doc_rows
        ]
    )
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="a", depth=2)

    graph.blast_radius.assert_called_once_with("a", depth=2)


async def test_blast_radius_depth_capped_at_config_max() -> None:
    """depth > LOOM_BLAST_RADIUS_MAX_DEPTH is clamped silently."""
    with patch.dict(os.environ, {"LOOM_BLAST_RADIUS_MAX_DEPTH": "5"}):
        # Re-import to pick up the patched env value
        import importlib

        import loom.config as cfg
        import loom.query.blast_radius as br_mod

        importlib.reload(cfg)
        importlib.reload(br_mod)

        graph = MagicMock()
        graph.query = AsyncMock(
            side_effect=[
                [{"id": "b", "name": "fn_b", "path": "y.py", "kind": "function"}],
                [],
            ]
        )
        graph.blast_radius = AsyncMock(return_value=[])

        await br_mod.build_blast_radius_payload(graph, node_id="b", depth=99)

        call_args = graph.blast_radius.call_args
        actual_depth = call_args.kwargs.get("depth") or call_args.args[1]
        assert actual_depth <= 5

        # Restore originals
        importlib.reload(cfg)
        importlib.reload(br_mod)


async def test_blast_radius_returns_correct_root() -> None:
    """Return payload has correct root node data."""
    graph = MagicMock()
    graph.query = AsyncMock(
        side_effect=[
            [{"id": "c", "name": "fn_c", "path": "z.py", "kind": "function"}],
            [],
        ]
    )
    graph.blast_radius = AsyncMock(return_value=[])

    result = await build_blast_radius_payload(graph, node_id="c", depth=3)

    assert result["root"]["id"] == "c"
    assert result["root"]["name"] == "fn_c"


async def test_blast_radius_missing_root_returns_empty() -> None:
    """Unknown node_id returns a zeroed payload, not an exception."""
    graph = MagicMock()
    graph.query = AsyncMock(return_value=[])
    graph.blast_radius = AsyncMock(return_value=[])

    result = await build_blast_radius_payload(graph, node_id="no_such_node", depth=3)

    assert result["root"] is None
    assert result["summary"]["total_nodes"] == 0
    graph.blast_radius.assert_not_called()


async def test_blast_radius_depth_never_exceeds_default_max() -> None:
    """With no explicit depth, depth defaults to LOOM_BLAST_RADIUS_MAX_DEPTH."""
    from loom.config import LOOM_BLAST_RADIUS_MAX_DEPTH

    graph = MagicMock()
    graph.query = AsyncMock(
        side_effect=[
            [{"id": "d", "name": "fn_d", "path": "w.py", "kind": "function"}],
            [],
        ]
    )
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="d")

    call_args = graph.blast_radius.call_args
    actual_depth = call_args.kwargs.get("depth") or call_args.args[1]
    assert actual_depth <= LOOM_BLAST_RADIUS_MAX_DEPTH
