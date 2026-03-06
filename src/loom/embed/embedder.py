from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from loom.core import Node


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class FastEmbedder:
    model: str = "nomic-ai/nomic-embed-text-v1.5"

    def embed(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding  # type: ignore

        emb = TextEmbedding(model_name=self.model)
        return [list(v) for v in emb.embed(texts)]


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

    vectors = embedder.embed(texts)
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
