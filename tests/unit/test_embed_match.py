from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource
from loom.embed.embedder import embed_nodes
from loom.linker.embed_match import link_by_embedding


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        # Very small deterministic vectors.
        out = []
        for t in texts:
            if "password" in t.lower():
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out


import pytest


@pytest.mark.asyncio
async def test_embed_nodes_sets_embedding(tmp_path):
    n = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="does password hashing",
        metadata={},
    )
    out = await embed_nodes([n], embedder=_FakeEmbedder())
    assert out[0].embedding == [1.0, 0.0]


@pytest.mark.asyncio
async def test_link_by_embedding_emits_edge_above_threshold(monkeypatch):
    code = Node(
        id="function:x:hash_pw",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="hash_pw",
        path="x",
        summary="hashes password with bcrypt",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:sec",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Password policy",
        path="spec.md",
        summary="Password must be hashed.",
        metadata={},
    )

    from loom import embed as _embed_pkg

    # Force embed_nodes in embed_match to use fake embedder by pre-setting embeddings.
    code = code.model_copy(update={"embedding": [1.0, 0.0]})
    doc = doc.model_copy(update={"embedding": [1.0, 0.0]})

    edges = await link_by_embedding([code], [doc], threshold=0.75)
    assert edges
    assert edges[0].link_method == "embed_match"
