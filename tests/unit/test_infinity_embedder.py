"""Tests for AsyncEmbedder protocol and InfinityEmbedder singleton."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


async def test_async_embedder_protocol_satisfied() -> None:
    """A class with async embed() satisfies AsyncEmbedder without importing infinity-emb."""
    from loom.embed.embedder import AsyncEmbedder

    class _FakeAsync:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 768 for _ in texts]

    assert isinstance(_FakeAsync(), AsyncEmbedder)


async def test_infinity_embedder_initializes_engine_once() -> None:
    """InfinityEmbedder must init the engine singleton only once across calls."""
    fake_engine = AsyncMock()
    fake_engine.embed = AsyncMock(return_value=([[0.2] * 768], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    engine_created = 0

    def fake_from_args(args: object) -> AsyncMock:
        nonlocal engine_created
        engine_created += 1
        return fake_engine

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.LOOM_EMBED_DIM", 768):
                try:
                    from infinity_emb import AsyncEmbeddingEngine  # type: ignore

                    with patch.object(AsyncEmbeddingEngine, "from_args", side_effect=fake_from_args):
                        from loom.embed.embedder import InfinityEmbedder

                        ie = InfinityEmbedder()
                        await ie.embed(["hello"])
                        await ie.embed(["world"])
                except ImportError:
                    pytest.skip("infinity-emb not installed")

    assert engine_created <= 1, "Engine was created more than once — singleton broken"


async def test_infinity_embedder_validates_dim() -> None:
    """InfinityEmbedder raises ValueError if output dim != LOOM_EMBED_DIM."""
    try:
        import numpy as np
        from infinity_emb import AsyncEmbeddingEngine  # type: ignore
    except ImportError:
        pytest.skip("infinity-emb not installed")

    fake_engine = AsyncMock()
    # Return wrong dim (4 instead of 768)
    fake_engine.embed = AsyncMock(return_value=([np.array([0.1, 0.2, 0.3, 0.4])], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.LOOM_EMBED_DIM", 768):
                with patch.object(AsyncEmbeddingEngine, "from_args", return_value=fake_engine):
                    from loom.embed.embedder import InfinityEmbedder

                    ie = InfinityEmbedder()
                    with pytest.raises(ValueError, match="dimension mismatch"):
                        await ie.embed(["hello"])


async def test_infinity_embedder_returns_list_of_lists() -> None:
    """Output is list[list[float]], not numpy arrays."""
    try:
        import numpy as np
        from infinity_emb import AsyncEmbeddingEngine  # type: ignore
    except ImportError:
        pytest.skip("infinity-emb not installed")

    vec = np.array([0.5] * 768)
    fake_engine = AsyncMock()
    fake_engine.embed = AsyncMock(return_value=([vec], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.LOOM_EMBED_DIM", 768):
                with patch.object(AsyncEmbeddingEngine, "from_args", return_value=fake_engine):
                    from loom.embed.embedder import InfinityEmbedder

                    ie = InfinityEmbedder()
                    result = await ie.embed(["hello"])

    assert isinstance(result, list)
    assert isinstance(result[0], list)
    assert all(isinstance(v, float) for v in result[0])
