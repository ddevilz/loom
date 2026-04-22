# Embedding Speed: Composable Adapter Design

**Date:** 2026-04-18
**Status:** Approved

---

## Problem

Indexing a large codebase takes 3–6 hours, almost entirely in the embedding step. Root causes (from `docs/embedding-speed-research.md`):

1. `LOOM_EMBED_BATCH_SIZE=32` — 8× too small; 312 ONNX calls for 10k nodes
2. No `parallel=` arg — single process wastes all but one CPU core
3. No `intra_op_num_threads` — ONNX Runtime uses 1 thread per matmul
4. One `asyncio.to_thread` per 32-item batch — N thread dispatches instead of 1
5. No cache — unchanged nodes re-embedded on every run

---

## Goal

Reduce first-index time by 7–12× (CPU, ONNX) and make incremental re-runs near-free. Zero quality loss (same `nomic-embed-text-v1.5` model throughout).

> Note: the research doc cites "30-60x" for Tier 4 — that figure is for GPU (A10G). CPU-only infinity-emb (ONNX) achieves 7–12× over current. The cache layer makes re-runs near-free regardless of backend.

---

## Architecture

```
embed_nodes(nodes)
  │
  ├─ LOOM_EMBED_BACKEND=infinity
  │    └─ CachedEmbedder
  │         ├─ check diskcache keyed by content_hash → return hit
  │         └─ InfinityEmbedder (cache miss)
  │              └─ AsyncEmbeddingEngine (singleton, lazy-init, ONNX backend)
  │
  └─ LOOM_EMBED_BACKEND=fastembed (default)
       └─ FastEmbedder (improved: parallel=0, intra_op_num_threads, single thread dispatch)
```

**Default backend is `fastembed`** — safe without optional deps. Set `LOOM_EMBED_BACKEND=infinity` to opt into the faster path after installing `loom[fast]`.

---

## Components

### `AsyncEmbedder` protocol

```python
class AsyncEmbedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Parallel to the existing sync `Embedder` protocol. `embed_nodes()` accepts either; async path skips `asyncio.to_thread`.

---

### `FastEmbedder` improvements (Tier 2)

**Applied first — prerequisite for removing the batch loop in `embed_nodes()`.**

Changes to `FastEmbedder.embed()`:
- Pass `parallel=0` — all CPU cores via multiprocessing
- Set `intra_op_num_threads=os.cpu_count()` at `TextEmbedding` init — threads within each ONNX matmul
- `FastEmbedder.embed()` now accepts and forwards the full corpus; fastembed's internal batching handles chunking

Once these are in place, `embed_nodes()` collapses the outer batch loop to a single `asyncio.to_thread(embedder.embed, all_texts)` call. This is safe only because `FastEmbedder.embed` now handles batching and retry internally. Do not remove the outer loop before applying these changes.

---

### `InfinityEmbedder`

- Wraps `infinity_emb.AsyncEmbeddingEngine` with `engine="optimum"` (ONNX backend — same runtime as fastembed, no quality change).
- **Singleton:** module-level `_INFINITY_ENGINE: AsyncEmbeddingEngine | None`, initialized on first `embed()` call.
- **Init:** `engine.__aenter__()` called once at first use via `asyncio.Lock` (double-checked locking).
- **Teardown:** `atexit.register` a sync wrapper that calls the engine's cleanup. For `loom index` (short-lived), process exit is acceptable. For `loom serve` (long-lived MCP server), the atexit handler ensures clean ONNX Runtime shutdown.

```python
import atexit

def _shutdown_infinity_engine() -> None:
    if _INFINITY_ENGINE is not None:
        try:
            asyncio.get_event_loop().run_until_complete(_INFINITY_ENGINE.__aexit__(None, None, None))
        except Exception:
            pass  # best-effort cleanup

atexit.register(_shutdown_infinity_engine)
```

- Validates output dimension against `LOOM_EMBED_DIM` on first call.

---

### `CachedEmbedder`

- Decorator: wraps any `AsyncEmbedder`.
- **Cache key:** `f"v1:{model_name}:{content_hash}"` — model name prefix auto-invalidates when `LOOM_EMBED_MODEL` changes.
- **Cache miss path:** nodes where `content_hash is None` bypass cache and always go to the inner embedder.
- **Write-back guard:** after model call, embeddings are written to cache **only for nodes where `content_hash is not None`**. Nodes with `content_hash=None` are never written to cache (avoids `f"v1:{model}:None"` ghost keys).
- **Backend:** `diskcache.Cache` at `{LOOM_EMBED_CACHE_DIR}/embed_vectors` — subdirectory inside the existing fastembed model cache dir. `LOOM_EMBED_CACHE_DIR` already exists in `config.py` (default `~/.loom/fastembed_cache`); this spec reuses it.
- Size capped at `LOOM_EMBED_CACHE_SIZE_GB × 2^30` bytes (default 1 GB).
- Thread-safe: `diskcache` handles concurrent access internally.

---

### `embed_nodes()` changes

Current signature:
```python
async def embed_nodes(nodes: list[Node], *, embedder: Embedder | None = None) -> list[Node]:
```

New signature (backward compatible — same keyword arg, same default):
```python
async def embed_nodes(nodes: list[Node], *, embedder: AsyncEmbedder | Embedder | None = None) -> list[Node]:
```

Callers passing nothing or a `FastEmbedder()` are unaffected.

Internal dispatch:
- `embedder is None` → select from `LOOM_EMBED_BACKEND`:
  - `"fastembed"` → `FastEmbedder()` (sync path)
  - `"infinity"` → `CachedEmbedder(InfinityEmbedder())` (async path)
- Async path (`AsyncEmbedder`): `vectors = await embedder.embed(all_texts)` — one call, no loop
- Sync path (`Embedder`): `vectors = await asyncio.to_thread(embedder.embed, all_texts)` — one dispatch for full corpus (safe because `FastEmbedder.embed` now handles batching internally)

---

## Config

```python
# src/loom/config.py additions
LOOM_EMBED_BACKEND: str = os.getenv("LOOM_EMBED_BACKEND", "fastembed")
if LOOM_EMBED_BACKEND not in ("infinity", "fastembed"):
    raise ValueError(
        f"LOOM_EMBED_BACKEND must be 'infinity' or 'fastembed', got {LOOM_EMBED_BACKEND!r}"
    )

LOOM_EMBED_CACHE_SIZE_GB: int = int(os.getenv("LOOM_EMBED_CACHE_SIZE_GB", "1"))
# LOOM_EMBED_CACHE_DIR already exists — CachedEmbedder uses {LOOM_EMBED_CACHE_DIR}/embed_vectors
```

---

## Dependencies

```toml
# pyproject.toml

# Hard dep (always installed):
"diskcache>=5.6"   # CachedEmbedder — zero-overhead import, small package

# Optional extra [fast]:
[project.optional-dependencies]
fast = [
    "infinity-emb[optimum]>=0.0.54",
]
```

`infinity-emb[optimum]` is optional to avoid pulling PyTorch/ONNX Runtime into minimal installs. Default backend `fastembed` works without it. Install with `pip install "loom[fast]"` to enable.

---

## Files

| File | Change |
|------|--------|
| `src/loom/embed/embedder.py` | Add `AsyncEmbedder`, `InfinityEmbedder`, `CachedEmbedder`; improve `FastEmbedder` (Tier 2); update `embed_nodes()` |
| `src/loom/config.py` | Add `LOOM_EMBED_BACKEND`, `LOOM_EMBED_CACHE_SIZE_GB` |
| `pyproject.toml` | Add `diskcache` (hard dep), `infinity-emb[optimum]` (optional `[fast]` extra) |
| `tests/unit/test_cached_embedder.py` | Hit, miss, no-hash bypass, write-back guard, model-change invalidation |
| `tests/unit/test_infinity_embedder.py` | Singleton init, output shape, dimension validation, atexit registration |
| `tests/unit/test_fast_embedder.py` | Verify improved `FastEmbedder`: `parallel=0` forwarded, full-corpus call, single thread dispatch |

---

## Expected Throughput

| Configuration | Throughput | Speedup |
|---|---|---|
| Current (batch=32, no parallel) | ~150–250 texts/sec | 1× |
| FastEmbedder improved (Tier 2) | ~900–1,400 texts/sec | ~5–6× |
| InfinityEmbedder CPU (ONNX, dynamic batching) | ~1,200–1,800 texts/sec | ~7–12× |
| InfinityEmbedder GPU (A10G) | ~8,000–15,000 texts/sec | ~32–100× |
| Either backend + cache (incremental run) | near-∞ | model not called |

---

## What This Does Not Change

- Model: `nomic-embed-text-v1.5` — unchanged, no quality impact
- Similarity thresholds — unchanged
- FalkorDB storage schema — embeddings stored identically
- Public API of `embed_nodes()` — backward compatible (same signature, same default)
- `LOOM_EMBED_CACHE_DIR` semantics — existing fastembed model cache untouched; vector cache is a new subdirectory
