"""Tests for blast_radius payload builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from loom.core import Node, NodeKind, NodeSource
from loom.query.blast_radius import build_blast_radius_payload


@pytest.mark.asyncio
async def test_blast_radius_forwards_depth_to_graph(tmp_path: Path) -> None:
    graph = MagicMock()
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="a", depth=2)

    graph.blast_radius.assert_called_once_with("a", depth=2)


@pytest.mark.asyncio
async def test_blast_radius_payload_shape(tmp_path: Path) -> None:
    node = Node(
        id="function:src/a.py:caller",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="caller",
        path="src/a.py",
        language="python",
        metadata={},
    )
    node.depth = 1

    graph = MagicMock()
    graph.blast_radius = AsyncMock(return_value=[node])

    result = await build_blast_radius_payload(graph, node_id="function:src/a.py:f", depth=3)

    assert result["node_id"] == "function:src/a.py:f"
    assert result["depth"] == 3
    assert result["count"] == 1
    assert result["results"][0]["name"] == "caller"


@pytest.mark.asyncio
async def test_blast_radius_empty_returns_zero_count(tmp_path: Path) -> None:
    graph = MagicMock()
    graph.blast_radius = AsyncMock(return_value=[])

    result = await build_blast_radius_payload(graph, node_id="x", depth=3)

    assert result["count"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_blast_radius_default_depth_is_three() -> None:
    graph = MagicMock()
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="x")

    graph.blast_radius.assert_called_once_with("x", depth=3)
