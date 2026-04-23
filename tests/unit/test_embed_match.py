from __future__ import annotations

import pytest

from loom.core import Node, NodeKind, NodeSource
from loom.embed.embedder import embed_nodes
from loom.linker.embed_match import link_by_embedding


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        # 768-dimensional vectors to match LOOM_EMBED_DIM
        out = []
        for t in texts:
            if "password" in t.lower():
                # First dimension is 1.0, rest are 0.0
                out.append([1.0] + [0.0] * 767)
            else:
                # First dimension is 0.0, second is 1.0, rest are 0.0
                out.append([0.0, 1.0] + [0.0] * 766)
        return out


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
    assert out[0].embedding == [1.0] + [0.0] * 767


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

    # Force embed_nodes in embed_match to use fake embedder by pre-setting embeddings.
    code = code.model_copy(update={"embedding": [1.0, 0.0]})
    doc = doc.model_copy(update={"embedding": [1.0, 0.0]})

    edges = await link_by_embedding([code], [doc], threshold=0.75)
    assert edges
    assert edges[0].link_method == "embed_match"


@pytest.mark.asyncio
async def test_vector_index_failure_is_logged_not_silently_swallowed(caplog):
    """When the vector index query fails, a warning must be logged — not silently dropped."""
    import logging

    from loom.linker.embed_match import _candidate_doc_ids_from_vector_index

    code = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="does something",
        embedding=[1.0, 0.0],
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:sec",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Spec",
        path="spec.md",
        summary="spec text",
        embedding=[1.0, 0.0],
        metadata={},
    )

    class _FailingGraph:
        async def query(self, cypher, params=None):
            raise RuntimeError("vector index broken")

    with caplog.at_level(logging.WARNING, logger="loom.linker.embed_match"):
        result = await _candidate_doc_ids_from_vector_index(
            code, {doc.id: doc}, _FailingGraph()
        )

    # Returns None to signal fallback (correct), but must also log a warning
    assert result is None, "expected None on failure to trigger fallback"
    assert caplog.records, (
        "expected a warning log when vector index fails — "
        "silent swallow hides broken index from operators"
    )
