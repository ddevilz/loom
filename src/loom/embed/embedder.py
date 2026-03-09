from __future__ import annotations

import asyncio
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loom.config import LOOM_EMBED_BATCH_SIZE, LOOM_EMBED_CACHE_DIR, LOOM_EMBED_MODEL
from loom.core import Node

logger = logging.getLogger(__name__)


_EMBEDDER_CACHE: dict[str, object] = {}
_EMBEDDER_CACHE_LOCK = threading.Lock()


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
        # Fast path: check if model is already cached
        if self.model in _EMBEDDER_CACHE:
            emb = _EMBEDDER_CACHE[self.model]
        else:
            # Acquire lock for initialization
            with _EMBEDDER_CACHE_LOCK:
                # Double-check after acquiring lock (another thread may have initialized)
                if self.model not in _EMBEDDER_CACHE:
                    emb = TextEmbedding(model_name=self.model, cache_dir=str(cache_dir))
                    _EMBEDDER_CACHE[self.model] = emb
                else:
                    emb = _EMBEDDER_CACHE[self.model]

        try:
            return [list(v) for v in emb.embed(texts)]
        except Exception as e:
            # On error, recreate the embedder (thread-safe)
            logger.warning(
                f"Embedding failed with model {self.model}: {e}. "
                f"Recreating embedder and retrying. Text count: {len(texts)}"
            )
            with _EMBEDDER_CACHE_LOCK:
                emb = TextEmbedding(model_name=self.model, cache_dir=str(cache_dir))
                _EMBEDDER_CACHE[self.model] = emb
            try:
                return [list(v) for v in emb.embed(texts)]
            except Exception as retry_error:
                logger.error(
                    f"Embedding retry failed with model {self.model}: {retry_error}. "
                    f"Text count: {len(texts)}",
                    exc_info=True,
                )
                raise


async def embed_nodes(
    nodes: list[Node],
    *,
    embedder: Embedder | None = None,
) -> list[Node]:
    to_embed: list[int] = []
    texts: list[str] = []

    for i, n in enumerate(nodes):
        if n.embedding is not None:
            continue
        if not isinstance(n.summary, str) or not n.summary.strip():
            continue
        to_embed.append(i)
        texts.append(n.summary)

    if not texts:
        return nodes

    if embedder is None:
        embedder = FastEmbedder()

    batch_size = max(1, LOOM_EMBED_BATCH_SIZE)
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(await asyncio.to_thread(embedder.embed, batch))

    if len(vectors) != len(texts):
        raise ValueError("embedder returned wrong number of vectors")

    # Validate embedding dimensions match configuration
    from loom.config import LOOM_EMBED_DIM

    if vectors and len(vectors[0]) != LOOM_EMBED_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: model produced {len(vectors[0])} dimensions "
            f"but LOOM_EMBED_DIM is configured as {LOOM_EMBED_DIM}. "
            f"Please update LOOM_EMBED_DIM to match your model."
        )

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
