"""Tests for CachedEmbedder diskcache decorator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "embed_cache"


def _make_inner(return_value: list[list[float]]) -> MagicMock:
    """Create a mock inner embedder whose .embed() is an AsyncMock."""
    inner = MagicMock()
    inner.embed = AsyncMock(return_value=return_value)
    return inner


async def test_cache_hit_skips_inner_embedder(tmp_cache_dir: Path) -> None:
    """Second call with same content_hash must not call inner embedder."""
    import diskcache

    inner = _make_inner([[0.5] * 768])
    cache = diskcache.Cache(str(tmp_cache_dir))
    cache["v1:nomic-ai/nomic-embed-text-v1.5:abc123"] = [0.5] * 768

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        from loom.embed.embedder import CachedEmbedder

        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=["abc123"])

    inner.embed.assert_not_called()
    assert result == [[0.5] * 768]


async def test_cache_miss_calls_inner_and_writes_back(tmp_cache_dir: Path) -> None:
    """Cache miss: inner embedder is called and result is written to cache."""
    import diskcache

    vec = [0.9] * 768
    inner = _make_inner([vec])
    cache = diskcache.Cache(str(tmp_cache_dir))

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        from loom.embed.embedder import CachedEmbedder

        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=["def456"])

    inner.embed.assert_called_once()
    assert result == [vec]
    assert cache.get("v1:nomic-ai/nomic-embed-text-v1.5:def456") == vec


async def test_none_content_hash_bypasses_cache_read_and_write(tmp_cache_dir: Path) -> None:
    """Nodes without content_hash bypass cache on both read and write-back."""
    import diskcache

    vec = [0.3] * 768
    inner = _make_inner([vec])
    cache = diskcache.Cache(str(tmp_cache_dir))

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        from loom.embed.embedder import CachedEmbedder

        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=[None])

    inner.embed.assert_called_once()
    assert result == [vec]
    assert len(list(cache)) == 0


async def test_model_change_invalidates_cache(tmp_cache_dir: Path) -> None:
    """Different model name in key means different key — old entry not returned."""
    import diskcache

    cache = diskcache.Cache(str(tmp_cache_dir))
    cache["v1:old-model:abc123"] = [0.1] * 768

    vec = [0.7] * 768
    inner = _make_inner([vec])

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "new-model"):
        from loom.embed.embedder import CachedEmbedder

        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=["abc123"])

    inner.embed.assert_called_once()
    assert result == [vec]


async def test_mixed_hits_and_misses(tmp_cache_dir: Path) -> None:
    """Batch with some cached and some uncached texts: only misses go to model."""
    import diskcache

    cache = diskcache.Cache(str(tmp_cache_dir))
    hit_vec = [0.1] * 768
    miss_vec = [0.9] * 768
    cache["v1:model:hash_hit"] = hit_vec

    inner = _make_inner([miss_vec])

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "model"):
        from loom.embed.embedder import CachedEmbedder

        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(
            ["cached text", "new text"], content_hashes=["hash_hit", "hash_miss"]
        )

    inner.embed.assert_called_once_with(["new text"])
    assert result == [hit_vec, miss_vec]
