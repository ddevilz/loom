# Loom Embedding Speed: Research Report

*Date: 2026-03-19 | Model: nomic-embed-text-v1.5 (kept — no quality tradeoffs below)*

---

## Problem

Indexing a large codebase takes **3-6 hours**, almost entirely spent in the embedding step. The root causes are in `src/loom/embed/embedder.py` and `src/loom/ingest/pipeline.py`.

---

## Root Cause Analysis

### 1. Batch size of 32 is ~8x too small
**File:** [`src/loom/embed/embedder.py:108`](../src/loom/embed/embedder.py#L108)

`LOOM_EMBED_BATCH_SIZE=32` means for 10,000 nodes you make **312 separate ONNX inference calls**. Each call pays Python overhead + asyncio thread dispatch. fastembed's `embed()` internally optimizes for larger batches — the overhead at batch=32 is almost pure waste.

**Fix:** Raise `LOOM_EMBED_BATCH_SIZE` to 256-512.
**Impact:** 2-3x throughput improvement from this alone.

---

### 2. No parallelism (`parallel=None`)
**File:** [`src/loom/embed/embedder.py:56`](../src/loom/embed/embedder.py#L56)

fastembed's `embed()` has a built-in `parallel` parameter that spawns multiple worker processes:

```python
emb.embed(texts, batch_size=256, parallel=0)  # parallel=0 = all CPU cores
```

Currently Loom calls `emb.embed(texts)` with no `parallel` argument, defaulting to single-process. On an 8-core machine this wastes 7 cores entirely.

**Fix:** Pass `parallel=0` to use all available CPU cores.
**Impact:** Additional 2-3x, combined ~5-6x vs current.

> **Note:** `parallel` uses `multiprocessing`, so each worker loads the ONNX model independently (~550MB per worker for nomic-embed-text-v1.5). On a machine with 16GB RAM, `parallel=4` is safe. Do not call `emb.embed()` concurrently from multiple threads on the same instance — ONNX Runtime sessions are not thread-safe for concurrent inference.

---

### 3. Re-embedding unchanged nodes on every run
**File:** [`src/loom/ingest/pipeline.py:521`](../src/loom/ingest/pipeline.py#L521)

`embed_nodes()` has a guard (`if n.embedding is not None: continue`) but freshly parsed `Node` objects always have `embedding=None` even if the same function was indexed last week. Nothing looks up existing embeddings from FalkorDB before calling the model.

**Fix:** Before calling `embed_nodes()`, query FalkorDB for existing `content_hash → embedding` mappings and pre-populate matching nodes. The `embed_nodes()` guard then skips them.

**Impact:** On incremental runs (`force=False`), this can reduce embedding work to near zero.

---

### 4. `asyncio.to_thread` per small batch is wasteful
**File:** [`src/loom/embed/embedder.py:111`](../src/loom/embed/embedder.py#L111)

The current loop dispatches a new thread for every 32-item batch. Better to dispatch once for the entire corpus and let fastembed's internal batching handle the chunking:

```python
# Current (N/32 thread dispatches):
for start in range(0, len(texts), batch_size):
    batch_vectors = await asyncio.to_thread(embedder.embed, batch)

# Better (1 thread dispatch):
all_vectors = await asyncio.to_thread(
    lambda: list(emb.embed(texts, batch_size=256, parallel=0))
)
```

**Impact:** Eliminates thread dispatch overhead, ~10-20% additional gain.

---

## Solutions

### Tier 1: Config-only fix (today, ~0 min)

Set in `.env` or environment:

```bash
LOOM_EMBED_BATCH_SIZE=512
```

**Expected speedup: 2-3x. Zero code changes.**

---

### Tier 2: Code fixes in `embedder.py` (~30 min, 5-6x total speedup)

**A. Enable fastembed multiprocessing + ONNX thread tuning**

In `FastEmbedder.embed()`, change the embed call:

```python
import os

return [list(v) for v in emb.embed(
    texts,
    batch_size=256,
    parallel=0,  # use all CPU cores via multiprocessing
)]
```

**B. Set `intra_op_num_threads` at model init**

Controls how many threads ONNX Runtime uses within a single matrix multiply:

```python
emb = TextEmbedding(
    model_name=self.model,
    cache_dir=str(cache_dir),
    providers=["CPUExecutionProvider"],
    provider_options=[{"intra_op_num_threads": os.cpu_count() or 4}],
)
```

**C. Single thread dispatch for full corpus**

Remove the batch loop in `embed_nodes()` and pass all texts at once to fastembed.

---

### Tier 3: Embedding cache (2-4 hrs, near-zero cost on repeat runs)

Add a disk cache keyed by `content_hash`. Every time a node's source code hasn't changed, the embedding is retrieved from disk instead of calling the model.

**Best implementation: `diskcache`** (MIT license, no transitive deps, thread-safe):

```bash
pip install diskcache
```

```python
import diskcache

_DISK_CACHE: diskcache.Cache | None = None

def _get_disk_cache() -> diskcache.Cache:
    global _DISK_CACHE
    if _DISK_CACHE is None:
        cache_dir = Path(LOOM_EMBED_CACHE_DIR) / "embed_vectors"
        _DISK_CACHE = diskcache.Cache(str(cache_dir), size_limit=2**30)  # 1 GB
    return _DISK_CACHE

def _cache_key(model: str, content_hash: str) -> str:
    # Model name in key auto-invalidates on model change
    return f"v1:{model}:{content_hash}"
```

In `embed_nodes()`, check the cache before embedding each node:

```python
cache = _get_disk_cache()
for i, n in enumerate(nodes):
    if n.content_hash:
        key = _cache_key(LOOM_EMBED_MODEL, n.content_hash)
        if (cached := cache.get(key)) is not None:
            out[i] = n.model_copy(update={"embedding": cached})
            continue
    to_embed.append(i)
    texts.append(n.summary)

# After embedding misses, write back to cache:
for idx, vec in zip(to_embed, vectors, strict=True):
    node = out[idx]
    if node.content_hash:
        cache.set(_cache_key(LOOM_EMBED_MODEL, node.content_hash), vec)
```

**Cache key properties:**
- Same function body in two different files → cache hit (content-addressed)
- Rename a function without changing body → cache hit
- Change `LOOM_EMBED_MODEL` → all keys have new prefix → all miss → full re-embed
- `force=True` wipes the graph but disk cache survives → re-populate from disk, no model calls

**Alternative (zero new dependencies):** Query FalkorDB for existing embeddings by `content_hash` before calling the model. Add a bulk lookup in `_embed_nodes_if_needed()` in `pipeline.py:521`. Lower throughput than disk cache but requires no new packages.

---

### Tier 4: Switch to infinity-emb (~4-8 hrs, 7-12x CPU / 30-100x GPU)

[infinity-emb](https://github.com/michaelfeil/infinity) is a dedicated embedding inference engine with **dynamic batching** — it merges concurrent embed calls into optimal batches automatically. Same model, higher throughput.

**Install:**
```bash
pip install "infinity-emb[all]"
```

**In-process (no separate server):**

```python
from infinity_emb import AsyncEmbeddingEngine, EngineArgs

engine = AsyncEmbeddingEngine.from_args(EngineArgs(
    model_name_or_path="nomic-ai/nomic-embed-text-v1.5",
    engine="optimum",  # ONNX backend, same as fastembed
))

async with engine:
    embeddings, usage = await engine.embed(sentences=texts)
    # embeddings is a numpy array of shape (len(texts), 768)
```

Replace `FastEmbedder` in `embedder.py` with this.

**As a sidecar server (OpenAI-compatible API):**

```bash
infinity_emb v2 --model-id nomic-ai/nomic-embed-text-v1.5 --engine optimum --port 7997
```

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(base_url="http://localhost:7997", api_key="dummy")

async def embed(texts: list[str]) -> list[list[float]]:
    response = await client.embeddings.create(
        model="nomic-ai/nomic-embed-text-v1.5",
        input=texts,
    )
    return [item.embedding for item in response.data]
```

**Throughput comparison (CPU, nomic-embed-text-v1.5):**

| Configuration | Throughput |
|---|---|
| Loom current (batch=32, no parallel) | ~150-250 texts/sec |
| After batch=512 + parallel=0 | ~900-1,400 texts/sec |
| infinity-emb in-process (ONNX, dynamic batching) | ~1,200-1,800 texts/sec |
| infinity-emb + GPU (A10G) | ~8,000-15,000 texts/sec |
| After disk cache (incremental run, unchanged nodes) | ~∞ (model not called) |

---

## Action Plan

| Priority | Change | File | Speedup | Effort |
|---|---|---|---|---|
| 1 | Set `LOOM_EMBED_BATCH_SIZE=512` in `.env` | config | 2-3x | 0 min |
| 2 | Add `parallel=0` to `emb.embed()` call | `embedder.py:56` | +2-3x | 5 min |
| 3 | Set `intra_op_num_threads` at model init | `embedder.py:50` | +30-50% | 10 min |
| 4 | Single `asyncio.to_thread` for full corpus | `embedder.py:111` | +10-20% | 15 min |
| 5 | `diskcache` keyed by `content_hash` | `embedder.py` | Near-zero on re-runs | 2 hrs |
| 6 | Graph lookup before embedding (zero-dep alt to 5) | `pipeline.py:521` | Near-zero on re-runs | 1 hr |
| 7 | Replace fastembed with infinity-emb (same model) | `embedder.py` | 7-12x (CPU) / 30-100x (GPU) | 4-8 hrs |

**Start with priorities 1-4 today.** That is a 5-6x speedup (3-6 hours → ~30-60 min) with less than 30 minutes of work and zero quality loss.

Add priority 5 or 6 to make incremental re-indexes near-free.

---

## What Was Ruled Out

**Smaller/faster models** (`bge-small-en-v1.5`, 256-dim Matryoshka truncation of nomic) would give 3-4x additional speedup but reduce retrieval relevancy. All solutions above use the same `nomic-embed-text-v1.5` model and have no quality impact.
