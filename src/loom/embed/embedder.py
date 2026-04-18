from __future__ import annotations

import asyncio
import atexit
import logging
import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from loom.config import (
    LOOM_EMBED_BACKEND,
    LOOM_EMBED_CACHE_DIR,
    LOOM_EMBED_CACHE_SIZE_GB,
    LOOM_EMBED_DIM,
    LOOM_EMBED_ENABLED,
    LOOM_EMBED_MODEL,
)
from loom.core import Node

logger = logging.getLogger(__name__)


_EMBEDDER_CACHE: dict[str, object] = {}
_EMBEDDER_CACHE_LOCK = threading.Lock()

# InfinityEmbedder singleton state
_INFINITY_ENGINE: object = None
_INFINITY_ENGINE_LOCK: asyncio.Lock | None = None


def _get_infinity_lock() -> asyncio.Lock:
    global _INFINITY_ENGINE_LOCK
    if _INFINITY_ENGINE_LOCK is None:
        _INFINITY_ENGINE_LOCK = asyncio.Lock()
    return _INFINITY_ENGINE_LOCK


def _shutdown_infinity_engine() -> None:
    global _INFINITY_ENGINE
    if _INFINITY_ENGINE is not None:
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_INFINITY_ENGINE.__aexit__(None, None, None))
            loop.close()
        except Exception:
            pass  # best-effort


atexit.register(_shutdown_infinity_engine)


@runtime_checkable
class AsyncEmbedder(Protocol):
    async def embed(
        self,
        texts: list[str],
        *,
        content_hashes: list[str | None] | None = None,
    ) -> list[list[float]]: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class FastEmbedder:
    model: str = LOOM_EMBED_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding  # type: ignore

        cache_dir = Path(LOOM_EMBED_CACHE_DIR)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Thread-safe cache access with double-checked locking
        if self.model in _EMBEDDER_CACHE:
            emb = _EMBEDDER_CACHE[self.model]
        else:
            with _EMBEDDER_CACHE_LOCK:
                if self.model not in _EMBEDDER_CACHE:
                    emb = TextEmbedding(
                        model_name=self.model,
                        cache_dir=str(cache_dir),
                        providers=["CPUExecutionProvider"],
                        provider_options=[{"intra_op_num_threads": os.cpu_count() or 4}],
                    )
                    _EMBEDDER_CACHE[self.model] = emb
                else:
                    emb = _EMBEDDER_CACHE[self.model]

        try:
            return [list(v) for v in emb.embed(texts, parallel=0)]
        except Exception as e:
            logger.warning(
                "Embedding failed with model %s: %s. "
                "Recreating embedder and retrying. Text count: %d",
                self.model,
                e,
                len(texts),
            )
            with _EMBEDDER_CACHE_LOCK:
                emb = TextEmbedding(
                    model_name=self.model,
                    cache_dir=str(cache_dir),
                    providers=["CPUExecutionProvider"],
                    provider_options=[{"intra_op_num_threads": os.cpu_count() or 4}],
                )
                _EMBEDDER_CACHE[self.model] = emb
            try:
                return [list(v) for v in emb.embed(texts, parallel=0)]
            except Exception as retry_error:
                logger.error(
                    "Embedding retry failed with model %s: %s. Text count: %d",
                    self.model,
                    retry_error,
                    len(texts),
                    exc_info=True,
                )
                raise


class InfinityEmbedder:
    """AsyncEmbedder backed by infinity-emb AsyncEmbeddingEngine (ONNX, in-process)."""

    async def _get_engine(self) -> object:
        global _INFINITY_ENGINE
        if _INFINITY_ENGINE is not None:
            return _INFINITY_ENGINE
        try:
            from infinity_emb import AsyncEmbeddingEngine, EngineArgs  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "infinity-emb is required for LOOM_EMBED_BACKEND=infinity. "
                "Install with: pip install 'infinity-emb[optimum]'"
            ) from exc
        lock = _get_infinity_lock()
        async with lock:
            if _INFINITY_ENGINE is None:
                engine = AsyncEmbeddingEngine.from_args(
                    EngineArgs(
                        model_name_or_path=LOOM_EMBED_MODEL,
                        engine="optimum",
                    )
                )
                await engine.__aenter__()
                _INFINITY_ENGINE = engine  # type: ignore
        return _INFINITY_ENGINE

    async def embed(
        self,
        texts: list[str],
        *,
        content_hashes: list[str | None] | None = None,
    ) -> list[list[float]]:
        engine = await self._get_engine()
        embeddings, _ = await engine.embed(sentences=texts)
        vectors = [list(map(float, v)) for v in embeddings]
        if vectors and len(vectors[0]) != LOOM_EMBED_DIM:
            raise ValueError(
                f"Embedding dimension mismatch: InfinityEmbedder produced "
                f"{len(vectors[0])} dimensions but LOOM_EMBED_DIM={LOOM_EMBED_DIM}."
            )
        return vectors


@dataclass
class CachedEmbedder:
    """Decorator that caches embeddings to disk, keyed by content_hash."""

    inner: AsyncEmbedder
    cache: object = field(default=None)

    def _get_cache(self) -> object:
        if self.cache is not None:
            return self.cache
        import diskcache  # type: ignore

        cache_path = Path(LOOM_EMBED_CACHE_DIR) / "embed_vectors"
        cache_path.mkdir(parents=True, exist_ok=True)
        self.cache = diskcache.Cache(
            str(cache_path),
            size_limit=LOOM_EMBED_CACHE_SIZE_GB * (2**30),
        )
        return self.cache

    async def embed(
        self,
        texts: list[str],
        *,
        content_hashes: list[str | None] | None = None,
    ) -> list[list[float]]:
        if content_hashes is None:
            content_hashes = [None] * len(texts)
        cache = self._get_cache()
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        for i, (text, ch) in enumerate(zip(texts, content_hashes, strict=True)):
            if ch is None:
                miss_indices.append(i)
                miss_texts.append(text)
                continue
            key = f"v1:{LOOM_EMBED_MODEL}:{ch}"
            cached = cache.get(key)
            if cached is not None:
                results[i] = cached
            else:
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            miss_vectors = await self.inner.embed(miss_texts)
            for orig_idx, vec in zip(miss_indices, miss_vectors, strict=True):
                results[orig_idx] = vec
                ch = content_hashes[orig_idx]
                if ch is not None:
                    cache.set(f"v1:{LOOM_EMBED_MODEL}:{ch}", vec)

        return [v for v in results if v is not None]


async def embed_nodes(
    nodes: list[Node],
    *,
    embedder: AsyncEmbedder | Embedder | None = None,
) -> list[Node]:
    if not LOOM_EMBED_ENABLED:
        return nodes

    to_embed: list[int] = []
    texts: list[str] = []
    content_hashes: list[str | None] = []

    for i, n in enumerate(nodes):
        if n.embedding is not None:
            continue
        if not isinstance(n.summary, str) or not n.summary.strip():
            continue
        to_embed.append(i)
        texts.append(n.summary)
        content_hashes.append(n.content_hash if isinstance(n.content_hash, str) else None)

    if not texts:
        return nodes

    logger.info("Embedding %d node summaries...", len(texts))

    # Select backend
    if embedder is None:
        if LOOM_EMBED_BACKEND == "infinity":
            embedder = CachedEmbedder(InfinityEmbedder())
        else:
            embedder = FastEmbedder()

    # Dispatch: async embedder called directly; sync embedder wrapped in thread.
    # Use iscoroutinefunction — runtime_checkable Protocol only checks method presence,
    # not whether the method is actually a coroutine.
    if asyncio.iscoroutinefunction(embedder.embed):
        vectors: list[list[float]] = await embedder.embed(texts, content_hashes=content_hashes)
    else:
        vectors = await asyncio.to_thread(embedder.embed, texts)

    if vectors and len(vectors[0]) != LOOM_EMBED_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: model produced {len(vectors[0])} dimensions "
            f"but LOOM_EMBED_DIM is configured as {LOOM_EMBED_DIM}. "
            f"Please update LOOM_EMBED_DIM to match your model."
        )
    if len(vectors) != len(texts):
        raise ValueError("embedder returned wrong number of vectors")

    out = list(nodes)
    for idx, vec in zip(to_embed, vectors, strict=True):
        out[idx] = out[idx].model_copy(update={"embedding": vec})

    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))
