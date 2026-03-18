from __future__ import annotations

import logging

import pytest

from loom.core import Node, NodeKind, NodeSource


def _make_node(node_id: str, summary: str) -> Node:
    return Node(
        id=node_id,
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=node_id,
        path="x.py",
        summary=summary,
        metadata={},
    )


@pytest.mark.asyncio
async def test_embed_nodes_progress_uses_logger_not_print(caplog, capsys):
    """embed_nodes must use logger.info for progress, not print()."""
    from loom.embed.embedder import embed_nodes

    calls: list[list[str]] = []

    class _FakeEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[0.1] * 768 for _ in texts]

    nodes = [_make_node(f"function:x:fn{i}", f"summary text {i}") for i in range(3)]

    with caplog.at_level(logging.INFO, logger="loom.embed.embedder"):
        await embed_nodes(nodes, embedder=_FakeEmbedder())

    captured = capsys.readouterr()
    assert captured.out == "", (
        "embed_nodes wrote to stdout via print() — must use logger.info() instead"
    )
    assert any("Embedding" in r.message for r in caplog.records), (
        "embed_nodes emitted no INFO log — progress must be logged"
    )
