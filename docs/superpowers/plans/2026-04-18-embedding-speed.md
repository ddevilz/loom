# Embedding Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slow single-threaded fastembed batch loop with a composable adapter stack (improved FastEmbedder + InfinityEmbedder + diskcache) to cut first-index time by 5–12× and make incremental re-runs near-free.

**Architecture:** `embed_nodes()` dispatches to either an improved `FastEmbedder` (sync, default) or `CachedEmbedder(InfinityEmbedder())` (async, opt-in via `LOOM_EMBED_BACKEND=infinity`). A `diskcache` layer keyed by `content_hash` short-circuits the model entirely for unchanged nodes.

**Tech Stack:** Python 3.12, fastembed, infinity-emb[optimum] (optional), diskcache, asyncio

---

## File Map

| File | Role |
|------|------|
| `src/loom/embed/embedder.py` | All embedding code: protocols, implementations, `embed_nodes()` |
| `src/loom/config.py` | `LOOM_EMBED_BACKEND`, `LOOM_EMBED_CACHE_SIZE_GB` |
| `pyproject.toml` | `diskcache` hard dep, `infinity-emb[optimum]` optional `[fast]` extra |
| `tests/unit/test_fast_embedder.py` | FastEmbedder Tier 2 improvements |
| `tests/unit/test_cached_embedder.py` | CachedEmbedder hit/miss/write-back/invalidation |
| `tests/unit/test_infinity_embedder.py` | InfinityEmbedder singleton, dim validation, atexit |
| `tests/unit/test_embedder.py` | Existing — must remain green throughout |

---

## Task 1: Config + Dependencies

**Files:**
- Modify: `src/loom/config.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add config constants**

In `src/loom/config.py`, after the existing `LOOM_LINKER_EMBED_THRESHOLD` block:

```python
# Embedding backend selection
LOOM_EMBED_BACKEND: str = os.getenv("LOOM_EMBED_BACKEND", "fastembed")
if LOOM_EMBED_BACKEND not in ("infinity", "fastembed"):
    raise ValueError(
        f"LOOM_EMBED_BACKEND must be 'infinity' or 'fastembed', got {LOOM_EMBED_BACKEND!r}"
    )

LOOM_EMBED_CACHE_SIZE_GB: int = int(os.getenv("LOOM_EMBED_CACHE_SIZE_GB", "1"))
```

- [ ] **Step 2: Add dependencies to pyproject.toml**

Add `diskcache` to the hard `dependencies` list:
```toml
"diskcache>=5.6",
```

Add `[fast]` optional extra below `[dependency-groups]`:
```toml
[project.optional-dependencies]
fast = [
    "infinity-emb[optimum]>=0.0.54",
]
```

- [ ] **Step 3: Install new dep**

```bash
uv pip install diskcache
```

- [ ] **Step 4: Verify config loads cleanly**

```bash
python -c "from loom.config import LOOM_EMBED_BACKEND, LOOM_EMBED_CACHE_SIZE_GB; print(LOOM_EMBED_BACKEND, LOOM_EMBED_CACHE_SIZE_GB)"
```

Expected output: `fastembed 1`

- [ ] **Step 5: Run existing tests to confirm no breakage**

```bash
uv run pytest tests/unit/test_embedder.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/loom/config.py pyproject.toml
git commit -m "feat: add LOOM_EMBED_BACKEND and LOOM_EMBED_CACHE_SIZE_GB config, diskcache dep, [fast] optional extra"
```

---

## Task 2: Improve FastEmbedder (Tier 2)

Prerequisite for Task 3 — must land before the batch loop is removed.

**Files:**
- Modify: `src/loom/embed/embedder.py`
- Create: `tests/unit/test_fast_embedder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_fast_embedder.py`:

```python
"""Tests for improved FastEmbedder (Tier 2: parallel, intra_op_num_threads, full-corpus)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

import pytest


def test_fast_embedder_passes_parallel_zero() -> None:
    """FastEmbedder.embed() must pass parallel=0 to emb.embed()."""
    mock_emb = MagicMock()
    mock_emb.embed.return_value = iter([[0.1] * 768, [0.2] * 768])

    with patch("loom.embed.embedder._EMBEDDER_CACHE", {}) as _cache:
        with patch("loom.embed.embedder._EMBEDDER_CACHE_LOCK"):
            with patch("fastembed.TextEmbedding", return_value=mock_emb):
                from loom.embed.embedder import FastEmbedder
                fe = FastEmbedder()
                result = fe.embed(["hello", "world"])

    call_kwargs = mock_emb.embed.call_args
    assert call_kwargs.kwargs.get("parallel") == 0 or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1] == 0
    ), "FastEmbedder.embed() did not pass parallel=0 to emb.embed()"


def test_fast_embedder_inits_with_intra_op_threads() -> None:
    """TextEmbedding must be initialised with intra_op_num_threads=os.cpu_count()."""
    mock_emb = MagicMock()
    mock_emb.embed.return_value = iter([[0.1] * 768])

    init_kwargs: dict = {}

    def capture_init(**kwargs):
        init_kwargs.update(kwargs)
        return mock_emb

    with patch("loom.embed.embedder._EMBEDDER_CACHE", {}):
        with patch("fastembed.TextEmbedding", side_effect=capture_init):
            from loom.embed.embedder import FastEmbedder
            FastEmbedder().embed(["hello"])

    provider_options = init_kwargs.get("provider_options", [{}])
    threads = provider_options[0].get("intra_op_num_threads") if provider_options else None
    assert threads == (os.cpu_count() or 4), (
        f"Expected intra_op_num_threads={os.cpu_count() or 4}, got {threads}"
    )


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
    first_call_texts = mock_emb.embed.call_args.args[0] if mock_emb.embed.call_args.args else mock_emb.embed.call_args.kwargs.get("texts") or mock_emb.embed.call_args.kwargs.get("documents")
    assert list(first_call_texts) == texts or len(list(mock_emb.embed.call_args.args[0])) == 100
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/unit/test_fast_embedder.py -v --tb=short
```

Expected: 3 failures (FastEmbedder doesn't yet pass `parallel=0`, `intra_op_num_threads`, or full corpus).

- [ ] **Step 3: Update FastEmbedder in `embedder.py`**

In `FastEmbedder.embed()` change the `TextEmbedding` initialization block and the embed call:

```python
import os  # add at top of file if not already present

# In _EMBEDDER_CACHE miss branch:
emb = TextEmbedding(
    model_name=self.model,
    cache_dir=str(cache_dir),
    providers=["CPUExecutionProvider"],
    provider_options=[{"intra_op_num_threads": os.cpu_count() or 4}],
)

# Replace the embed call (both the normal path and retry path):
return [list(v) for v in emb.embed(texts, parallel=0)]
```

The `embed()` method now receives the full corpus in one call; fastembed's internal batching handles chunking. Remove any references to `LOOM_EMBED_BATCH_SIZE` inside `FastEmbedder.embed()` (the config var can stay for the outer `embed_nodes()` loop which will be removed in Task 3).

- [ ] **Step 4: Run FastEmbedder tests — expect PASS**

```bash
uv run pytest tests/unit/test_fast_embedder.py -v --tb=short
```

Expected: 3 passes.

- [ ] **Step 5: Confirm existing embedder test still passes**

```bash
uv run pytest tests/unit/test_embedder.py -v --tb=short
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/loom/embed/embedder.py tests/unit/test_fast_embedder.py
git commit -m "perf: FastEmbedder Tier 2 — parallel=0, intra_op_num_threads, single full-corpus call"
```

---

## Task 3: Collapse `embed_nodes()` Batch Loop

**Requires Task 2 complete** — safe only because `FastEmbedder.embed()` now handles batching internally.

**Files:**
- Modify: `src/loom/embed/embedder.py`

- [ ] **Step 1: Write a test that will catch regression if batch loop returns**

Add to `tests/unit/test_embedder.py`:

```python
async def test_embed_nodes_calls_embedder_once_not_per_batch():
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

    nodes = [_make_node(f"fn{i}", f"summary {i}") for i in range(50)]
    await embed_nodes(nodes, embedder=_CountingEmbedder())

    assert call_count == 1, (
        f"embed_nodes called embedder.embed() {call_count} times — expected 1"
    )
    assert len(all_texts_received) == 50
```

- [ ] **Step 2: Run test — expect FAIL (current code calls embed once per 32-item batch)**

```bash
uv run pytest tests/unit/test_embedder.py::test_embed_nodes_calls_embedder_once_not_per_batch -v --tb=short
```

Expected: FAIL — `call_count` will be 2 (50 texts / 32 batch = 2 calls).

- [ ] **Step 3: Replace batch loop in `embed_nodes()` with single dispatch**

In `embed_nodes()`, replace the entire batch loop:

```python
# BEFORE (remove this):
batch_size = max(1, LOOM_EMBED_BATCH_SIZE)
vectors: list[list[float]] = []
num_batches = (len(texts) + batch_size - 1) // batch_size
for start in range(0, len(texts), batch_size):
    batch = texts[start : start + batch_size]
    logger.info("Embedding batch %d/%d (%d texts)...", ...)
    batch_vectors = await asyncio.to_thread(embedder.embed, batch)
    if batch_vectors and len(batch_vectors[0]) != LOOM_EMBED_DIM:
        raise ValueError(...)
    vectors.extend(batch_vectors)

# AFTER (replace with):
vectors: list[list[float]] = await asyncio.to_thread(embedder.embed, texts)
if vectors and len(vectors[0]) != LOOM_EMBED_DIM:
    raise ValueError(
        f"Embedding dimension mismatch: model produced {len(vectors[0])} dimensions "
        f"but LOOM_EMBED_DIM is configured as {LOOM_EMBED_DIM}. "
        f"Please update LOOM_EMBED_DIM to match your model."
    )
```

Keep the `if len(vectors) != len(texts): raise ValueError(...)` check after the call.

- [ ] **Step 4: Run all embedder tests**

```bash
uv run pytest tests/unit/test_embedder.py tests/unit/test_fast_embedder.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/loom/embed/embedder.py tests/unit/test_embedder.py
git commit -m "perf: collapse embed_nodes() batch loop to single asyncio.to_thread dispatch"
```

---

## Task 4: Add `CachedEmbedder`

**Files:**
- Modify: `src/loom/embed/embedder.py`
- Create: `tests/unit/test_cached_embedder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_cached_embedder.py`:

```python
"""Tests for CachedEmbedder diskcache decorator."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "embed_cache"


async def test_cache_hit_skips_inner_embedder(tmp_cache_dir: Path) -> None:
    """Second call with same content_hash must not call inner embedder."""
    import diskcache

    inner = AsyncMock(return_value=[[0.5] * 768])
    cache = diskcache.Cache(str(tmp_cache_dir))
    key = "v1:nomic-ai/nomic-embed-text-v1.5:abc123"
    cache[key] = [0.5] * 768

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        with patch("loom.embed.embedder.LOOM_EMBED_CACHE_DIR", str(tmp_cache_dir.parent)):
            from loom.embed.embedder import CachedEmbedder
            ce = CachedEmbedder(inner, cache=cache)
            result = await ce.embed(["hello"], content_hashes=["abc123"])

    inner.assert_not_called()
    assert result == [[0.5] * 768]


async def test_cache_miss_calls_inner_and_writes_back(tmp_cache_dir: Path) -> None:
    """Cache miss: inner embedder is called and result is written to cache."""
    import diskcache

    vec = [0.9] * 768
    inner = AsyncMock(return_value=[vec])
    cache = diskcache.Cache(str(tmp_cache_dir))

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        from loom.embed.embedder import CachedEmbedder
        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=["def456"])

    inner.assert_called_once()
    assert result == [vec]
    # Written to cache
    assert cache.get("v1:nomic-ai/nomic-embed-text-v1.5:def456") == vec


async def test_none_content_hash_bypasses_cache_read_and_write(tmp_cache_dir: Path) -> None:
    """Nodes without content_hash: bypass cache both on read and write-back."""
    import diskcache

    vec = [0.3] * 768
    inner = AsyncMock(return_value=[vec])
    cache = diskcache.Cache(str(tmp_cache_dir))

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5"):
        from loom.embed.embedder import CachedEmbedder
        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=[None])

    inner.assert_called_once()
    assert result == [vec]
    # Nothing written to cache (would need a None-containing key)
    assert len(list(cache)) == 0


async def test_model_change_invalidates_cache(tmp_cache_dir: Path) -> None:
    """Different model name in key means different key — old entry not returned."""
    import diskcache

    cache = diskcache.Cache(str(tmp_cache_dir))
    # Seed with old model
    cache["v1:old-model:abc123"] = [0.1] * 768

    vec = [0.7] * 768
    inner = AsyncMock(return_value=[vec])

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "new-model"):
        from loom.embed.embedder import CachedEmbedder
        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["hello"], content_hashes=["abc123"])

    # inner called — old key not reused
    inner.assert_called_once()
    assert result == [vec]


async def test_mixed_hits_and_misses(tmp_cache_dir: Path) -> None:
    """Batch with some cached and some uncached texts: only misses go to model."""
    import diskcache

    cache = diskcache.Cache(str(tmp_cache_dir))
    hit_vec = [0.1] * 768
    miss_vec = [0.9] * 768
    cache["v1:model:hash_hit"] = hit_vec

    inner = AsyncMock(return_value=[miss_vec])

    with patch("loom.embed.embedder.LOOM_EMBED_MODEL", "model"):
        from loom.embed.embedder import CachedEmbedder
        ce = CachedEmbedder(inner, cache=cache)
        result = await ce.embed(["cached text", "new text"], content_hashes=["hash_hit", "hash_miss"])

    inner.assert_called_once_with(["new text"])
    assert result == [hit_vec, miss_vec]
```

- [ ] **Step 2: Run tests — expect FAIL (CachedEmbedder doesn't exist yet)**

```bash
uv run pytest tests/unit/test_cached_embedder.py -v --tb=short
```

Expected: ImportError or NameError on `CachedEmbedder`.

- [ ] **Step 3: Implement `CachedEmbedder` in `embedder.py`**

Add after `FastEmbedder`:

```python
import atexit as _atexit


@dataclass
class CachedEmbedder:
    """Decorator that caches embeddings to disk, keyed by content_hash."""

    inner: AsyncEmbedder
    cache: object = None  # diskcache.Cache instance; created lazily if None

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
        content_hashes: list[str | None],
    ) -> list[list[float]]:
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
            for list_pos, (orig_idx, vec) in enumerate(
                zip(miss_indices, miss_vectors, strict=True)
            ):
                results[orig_idx] = vec
                ch = content_hashes[orig_idx]
                if ch is not None:
                    cache.set(f"v1:{LOOM_EMBED_MODEL}:{ch}", vec)

        return [v for v in results if v is not None]
```

- [ ] **Step 4: Run CachedEmbedder tests — expect PASS**

```bash
uv run pytest tests/unit/test_cached_embedder.py -v --tb=short
```

Expected: 5 passes.

- [ ] **Step 5: Run full unit suite**

```bash
uv run pytest tests/unit/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/loom/embed/embedder.py tests/unit/test_cached_embedder.py
git commit -m "feat: add CachedEmbedder diskcache decorator with content_hash keying and write-back guard"
```

---

## Task 5: Add `AsyncEmbedder` Protocol + `InfinityEmbedder`

**Files:**
- Modify: `src/loom/embed/embedder.py`
- Create: `tests/unit/test_infinity_embedder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_infinity_embedder.py`:

```python
"""Tests for AsyncEmbedder protocol and InfinityEmbedder singleton."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_async_embedder_protocol_satisfied() -> None:
    """A class with async embed() satisfies AsyncEmbedder without importing infinity-emb."""
    from loom.embed.embedder import AsyncEmbedder

    class _FakeAsync:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * 768 for _ in texts]

    # Protocol check — isinstance works with runtime_checkable protocols
    assert isinstance(_FakeAsync(), AsyncEmbedder)


async def test_infinity_embedder_initializes_engine_once() -> None:
    """InfinityEmbedder must init the engine singleton only once across calls."""
    fake_engine = AsyncMock()
    fake_engine.embed = AsyncMock(return_value=([[0.2] * 768], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    engine_created = 0

    def fake_from_args(args):
        nonlocal engine_created
        engine_created += 1
        return fake_engine

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.AsyncEmbeddingEngine") as mock_cls:
                mock_cls.from_args.side_effect = fake_from_args
                from loom.embed.embedder import InfinityEmbedder
                ie = InfinityEmbedder()
                await ie.embed(["hello"])
                await ie.embed(["world"])

    assert engine_created == 1, "Engine was created more than once — singleton broken"


async def test_infinity_embedder_validates_dim() -> None:
    """InfinityEmbedder raises ValueError if output dim != LOOM_EMBED_DIM."""
    import numpy as np

    fake_engine = AsyncMock()
    # Return wrong dim (4 instead of 768)
    fake_engine.embed = AsyncMock(return_value=([np.array([0.1, 0.2, 0.3, 0.4])], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.AsyncEmbeddingEngine") as mock_cls:
                mock_cls.from_args.return_value = fake_engine
                from loom.embed.embedder import InfinityEmbedder
                ie = InfinityEmbedder()
                with pytest.raises(ValueError, match="dimension mismatch"):
                    await ie.embed(["hello"])


async def test_infinity_embedder_returns_list_of_lists() -> None:
    """Output is list[list[float]], not numpy arrays."""
    import numpy as np

    vec = np.array([0.5] * 768)
    fake_engine = AsyncMock()
    fake_engine.embed = AsyncMock(return_value=([vec], None))
    fake_engine.__aenter__ = AsyncMock(return_value=fake_engine)
    fake_engine.__aexit__ = AsyncMock(return_value=None)

    with patch("loom.embed.embedder._INFINITY_ENGINE", None):
        with patch("loom.embed.embedder._INFINITY_ENGINE_LOCK", asyncio.Lock()):
            with patch("loom.embed.embedder.AsyncEmbeddingEngine") as mock_cls:
                mock_cls.from_args.return_value = fake_engine
                from loom.embed.embedder import InfinityEmbedder
                ie = InfinityEmbedder()
                result = await ie.embed(["hello"])

    assert isinstance(result, list)
    assert isinstance(result[0], list)
    assert all(isinstance(v, float) for v in result[0])
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/unit/test_infinity_embedder.py -v --tb=short
```

Expected: ImportError on `AsyncEmbedder`, `InfinityEmbedder`, `AsyncEmbeddingEngine`.

- [ ] **Step 3: Add `AsyncEmbedder` protocol and `InfinityEmbedder` to `embedder.py`**

Add `runtime_checkable` import and at the top of `embedder.py` (after existing `Protocol` import):

```python
import atexit
import asyncio
from typing import Protocol, runtime_checkable

@runtime_checkable
class AsyncEmbedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Add module-level singleton state (after `_EMBEDDER_CACHE_LOCK`):

```python
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
```

Add `InfinityEmbedder` class:

```python
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
                "Install with: pip install 'loom[fast]'"
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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        engine = await self._get_engine()
        embeddings, _ = await engine.embed(sentences=texts)
        vectors = [list(map(float, v)) for v in embeddings]
        if vectors and len(vectors[0]) != LOOM_EMBED_DIM:
            raise ValueError(
                f"Embedding dimension mismatch: InfinityEmbedder produced "
                f"{len(vectors[0])} dimensions but LOOM_EMBED_DIM={LOOM_EMBED_DIM}."
            )
        return vectors
```

- [ ] **Step 4: Run InfinityEmbedder tests — expect PASS**

```bash
uv run pytest tests/unit/test_infinity_embedder.py -v --tb=short
```

Expected: 4 passes.

- [ ] **Step 5: Run full unit suite**

```bash
uv run pytest tests/unit/ -q --tb=short
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/loom/embed/embedder.py tests/unit/test_infinity_embedder.py
git commit -m "feat: add AsyncEmbedder protocol and InfinityEmbedder singleton with atexit cleanup"
```

---

## Task 6: Wire `embed_nodes()` Dispatch

**Files:**
- Modify: `src/loom/embed/embedder.py`
- Modify: `tests/unit/test_embedder.py`

- [ ] **Step 1: Write failing test for backend dispatch**

Add to `tests/unit/test_embedder.py`:

```python
async def test_embed_nodes_uses_async_path_for_async_embedder():
    """AsyncEmbedder is awaited directly — asyncio.to_thread not used."""
    from loom.embed.embedder import embed_nodes, AsyncEmbedder

    call_count = 0

    class _FakeAsync:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            nonlocal call_count
            call_count += 1
            return [[0.1] * 768 for _ in texts]

    assert isinstance(_FakeAsync(), AsyncEmbedder)

    nodes = [_make_node("fn1", "summary one"), _make_node("fn2", "summary two")]
    result = await embed_nodes(nodes, embedder=_FakeAsync())

    assert call_count == 1
    assert all(n.embedding is not None for n in result)


async def test_embed_nodes_backend_fastembed_selects_fast_embedder(monkeypatch):
    """LOOM_EMBED_BACKEND=fastembed → FastEmbedder selected when embedder=None."""
    import loom.embed.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "LOOM_EMBED_BACKEND", "fastembed")

    created: list[str] = []

    class _FakeFastEmbedder:
        def embed(self, texts):
            created.append("fastembed")
            return [[0.1] * 768 for _ in texts]

    with patch("loom.embed.embedder.FastEmbedder", return_value=_FakeFastEmbedder()):
        from loom.embed.embedder import embed_nodes
        nodes = [_make_node("fn1", "summary")]
        await embed_nodes(nodes)

    assert "fastembed" in created


async def test_embed_nodes_backend_infinity_selects_cached_infinity(monkeypatch):
    """LOOM_EMBED_BACKEND=infinity → CachedEmbedder(InfinityEmbedder()) when embedder=None."""
    import loom.embed.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "LOOM_EMBED_BACKEND", "infinity")

    created: list[str] = []

    class _FakeInfinity:
        async def embed(self, texts):
            created.append("infinity")
            return [[0.1] * 768 for _ in texts]

    class _FakeCached:
        def __init__(self, inner, cache=None):
            self._inner = inner
        async def embed(self, texts, *, content_hashes=None):
            created.append("cached")
            return await self._inner.embed(texts)

    with patch("loom.embed.embedder.InfinityEmbedder", return_value=_FakeInfinity()):
        with patch("loom.embed.embedder.CachedEmbedder", _FakeCached):
            from loom.embed.embedder import embed_nodes
            nodes = [_make_node("fn1", "summary")]
            await embed_nodes(nodes)

    assert "cached" in created
    assert "infinity" in created
```

- [ ] **Step 2: Run — expect FAIL**

```bash
uv run pytest tests/unit/test_embedder.py -k "async_path or backend" -v --tb=short
```

- [ ] **Step 3: Update `embed_nodes()` signature and dispatch**

Replace the `embed_nodes()` function body in `embedder.py`:

```python
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

    # Dispatch: async embedder called directly; sync embedder wrapped in thread
    if isinstance(embedder, AsyncEmbedder):
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
```

> **Note:** `CachedEmbedder.embed()` accepts `content_hashes` keyword arg. The sync `Embedder` path does not use it (sync embedders have no cache awareness). This is intentional — the cache is only used with async backends.

- [ ] **Step 4: Run all embedder tests**

```bash
uv run pytest tests/unit/test_embedder.py tests/unit/test_fast_embedder.py tests/unit/test_cached_embedder.py tests/unit/test_infinity_embedder.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 5: Run full unit suite + lint + type check**

```bash
uv run pytest tests/unit/ -q --tb=short
uv run ruff check src/loom/embed/embedder.py
uv run mypy src/loom/embed/embedder.py --ignore-missing-imports
```

Expected: all pass, no errors.

- [ ] **Step 6: Commit**

```bash
git add src/loom/embed/embedder.py tests/unit/test_embedder.py
git commit -m "feat: wire embed_nodes() dispatch — async path for AsyncEmbedder, LOOM_EMBED_BACKEND selection"
```

---

## Final Verification

- [ ] **Full test suite**

```bash
uv run pytest tests/unit/ -q --tb=short
```

Expected: all tests pass (337+ tests).

- [ ] **mypy + ruff**

```bash
uv run mypy src/loom/ --ignore-missing-imports
uv run ruff check src/loom/
```

Expected: clean.

- [ ] **Smoke test default backend**

```bash
python -c "
import asyncio
from loom.embed.embedder import embed_nodes
from loom.core import Node, NodeKind, NodeSource

node = Node(id='t', kind=NodeKind.FUNCTION, source=NodeSource.CODE, name='t', path='t.py', summary='hello world', metadata={})
result = asyncio.run(embed_nodes([node]))
print('embedding dim:', len(result[0].embedding))
"
```

Expected: `embedding dim: 768`

---

## Summary

| Task | What | Commit message |
|------|------|----------------|
| 1 | Config + deps | `feat: add LOOM_EMBED_BACKEND, LOOM_EMBED_CACHE_SIZE_GB, diskcache dep` |
| 2 | FastEmbedder Tier 2 | `perf: FastEmbedder — parallel=0, intra_op_num_threads, single full-corpus call` |
| 3 | Collapse batch loop | `perf: collapse embed_nodes() batch loop to single asyncio.to_thread dispatch` |
| 4 | CachedEmbedder | `feat: add CachedEmbedder diskcache decorator` |
| 5 | InfinityEmbedder | `feat: add AsyncEmbedder protocol and InfinityEmbedder singleton` |
| 6 | Wire dispatch | `feat: wire embed_nodes() dispatch with backend selection` |
