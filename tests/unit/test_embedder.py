from __future__ import annotations

import logging
from unittest.mock import patch

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


@pytest.mark.asyncio
async def test_embed_nodes_calls_embedder_once_not_per_batch() -> None:
    """embed_nodes() must call embedder.embed() exactly once for the full corpus."""
    from loom.embed.embedder import embed_nodes

    call_count = 0
    all_texts_received: list[str] = []

    class _CountingEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            nonlocal call_count
            call_count += 1
            all_texts_received.extend(texts)
            return [[0.1] * 768 for _ in texts]

    nodes = [_make_node(f"function:x:fn{i}", f"summary {i}") for i in range(50)]
    await embed_nodes(nodes, embedder=_CountingEmbedder())

    assert call_count == 1, f"embed_nodes called embedder.embed() {call_count} times — expected 1"
    assert len(all_texts_received) == 50


@pytest.mark.asyncio
async def test_embed_nodes_uses_async_path_for_async_embedder() -> None:
    """AsyncEmbedder is awaited directly — no asyncio.to_thread."""
    from loom.embed.embedder import AsyncEmbedder, embed_nodes

    call_count = 0

    class _FakeAsync:
        async def embed(
            self, texts: list[str], *, content_hashes: list[str | None] | None = None
        ) -> list[list[float]]:
            nonlocal call_count
            call_count += 1
            return [[0.1] * 768 for _ in texts]

    assert isinstance(_FakeAsync(), AsyncEmbedder)

    nodes = [_make_node("function:x:fn1", "summary one"), _make_node("function:x:fn2", "summary two")]
    result = await embed_nodes(nodes, embedder=_FakeAsync())

    assert call_count == 1
    assert all(n.embedding is not None for n in result)


@pytest.mark.asyncio
async def test_embed_nodes_backend_fastembed_selects_fast_embedder(monkeypatch) -> None:
    """LOOM_EMBED_BACKEND=fastembed → FastEmbedder selected when embedder=None."""
    import loom.embed.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "LOOM_EMBED_BACKEND", "fastembed")

    created: list[str] = []

    class _FakeFastEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            created.append("fastembed")
            return [[0.1] * 768 for _ in texts]

    with patch("loom.embed.embedder.FastEmbedder", return_value=_FakeFastEmbedder()):
        from loom.embed.embedder import embed_nodes

        nodes = [_make_node("function:x:fn1", "summary")]
        await embed_nodes(nodes)

    assert "fastembed" in created


@pytest.mark.asyncio
async def test_embed_nodes_backend_infinity_selects_cached_infinity(monkeypatch) -> None:
    """LOOM_EMBED_BACKEND=infinity → CachedEmbedder(InfinityEmbedder()) when embedder=None."""
    import loom.embed.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "LOOM_EMBED_BACKEND", "infinity")

    created: list[str] = []

    class _FakeInfinity:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            created.append("infinity")
            return [[0.1] * 768 for _ in texts]

    class _FakeCached:
        def __init__(self, inner: object, cache: object = None) -> None:
            self._inner = inner

        async def embed(
            self,
            texts: list[str],
            *,
            content_hashes: list[str | None] | None = None,
        ) -> list[list[float]]:
            created.append("cached")
            return await self._inner.embed(texts)

    with patch("loom.embed.embedder.InfinityEmbedder", return_value=_FakeInfinity()):
        with patch("loom.embed.embedder.CachedEmbedder", _FakeCached):
            from loom.embed.embedder import embed_nodes

            nodes = [_make_node("function:x:fn1", "summary")]
            await embed_nodes(nodes)

    assert "cached" in created
    assert "infinity" in created
