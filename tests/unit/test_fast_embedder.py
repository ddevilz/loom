"""Tests for improved FastEmbedder (Tier 2: parallel, intra_op_num_threads, full-corpus)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def test_fast_embedder_passes_parallel_zero() -> None:
    """FastEmbedder.embed() must pass parallel=0 to emb.embed()."""
    mock_emb = MagicMock()
    mock_emb.embed.return_value = iter([[0.1] * 768, [0.2] * 768])

    with patch("loom.embed.embedder._EMBEDDER_CACHE", {"test-model": mock_emb}):
        from loom.embed.embedder import FastEmbedder

        fe = FastEmbedder(model="test-model")
        fe.embed(["hello", "world"])

    call_kwargs = mock_emb.embed.call_args
    passed_parallel = call_kwargs.kwargs.get("parallel")
    if passed_parallel is None and len(call_kwargs.args) > 1:
        passed_parallel = call_kwargs.args[1]
    assert passed_parallel == 0, f"FastEmbedder did not pass parallel=0, got {passed_parallel!r}"


def test_fast_embedder_inits_with_intra_op_threads() -> None:
    """TextEmbedding must be initialized with intra_op_num_threads=os.cpu_count()."""
    mock_emb = MagicMock()
    mock_emb.embed.return_value = iter([[0.1] * 768])

    captured_kwargs: dict = {}

    def capture_init(**kwargs: object) -> MagicMock:
        captured_kwargs.update(kwargs)
        return mock_emb

    with patch("loom.embed.embedder._EMBEDDER_CACHE", {}):
        with patch("fastembed.TextEmbedding", side_effect=capture_init):
            from loom.embed.embedder import FastEmbedder

            FastEmbedder().embed(["hello"])

    provider_options = captured_kwargs.get("provider_options", [{}])
    threads = provider_options[0].get("intra_op_num_threads") if provider_options else None
    expected = os.cpu_count() or 4
    assert threads == expected, f"Expected intra_op_num_threads={expected}, got {threads}"


def test_fast_embedder_passes_full_corpus_in_one_call() -> None:
    """FastEmbedder.embed() passes entire text list in a single emb.embed() call."""
    mock_emb = MagicMock()
    texts = [f"text {i}" for i in range(100)]
    mock_emb.embed.return_value = iter([[0.1] * 768 for _ in texts])

    with patch("loom.embed.embedder._EMBEDDER_CACHE", {"test-model": mock_emb}):
        from loom.embed.embedder import FastEmbedder

        fe = FastEmbedder(model="test-model")
        fe.embed(texts)

    assert mock_emb.embed.call_count == 1, (
        f"Expected 1 call to emb.embed(), got {mock_emb.embed.call_count}"
    )
