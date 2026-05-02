# Loom — Real-World Benchmark

Two repos. Real numbers. No mocking.

---

## Repos Tested

| Repo | Files | Languages | Source chars |
|------|-------|-----------|-------------|
| `replay-agent` | 35 src `.py` | Python | 88,448 |
| `finpower` | 678 src files | TS / TSX / JSX / Python / Go | 3,177,849 |

---

## The Core Loop (replay-agent walkthrough)

### Step 0 — Index (one-time)

```bash
cd ~/Desktop/replay-agent
loom analyze .
```

```
[scan]  discovering files (workers=8)
[scan]  done in 5s — 52 total, 52 changed
[parse] done in 5.1s — 387 nodes, 352 edges
[calls] done in 0.4s — 859 total edges
[write] done in 0.4s
[communities] Louvain done
```

DB written to `~/.loom/projects/replay-agent.db` (1.6 MB).
**Zero LLM calls. Zero cost.**

---

### Session 1 — Fresh index, no summaries yet

Agent gets a task: *"How does step recording work? Can it fail silently?"*

#### Call 1 — `search_code("add_step recorder")`

Response (no summary yet):

```json
[
  {
    "id": "method:src/replay/core/recorder.py:Recorder.add_step",
    "name": "add_step",
    "path": "src/replay/core/recorder.py",
    "kind": "method",
    "line": 80,
    "summary": null,
    "signature": "add_step(self, *, type: StepType, input: dict[str, Any], output: dict[str, Any], ...) -> Optional[Step]"
  }
]
```

**Tokens: ~433**
Summary is `null` — agent must read the source file.

---

#### Call 2 — Agent reads `recorder.py`

```
src/replay/core/recorder.py  →  4,370 chars  →  ~1,093 tokens
```

Agent reads the file, understands the function.

---

#### Call 3 — `store_understanding(node_id, summary)`

```json
{
  "node_id": "method:src/replay/core/recorder.py:Recorder.add_step",
  "summary": "Records a single LLM step into the run — computes cost, applies redaction, increments step index, and silently drops the step if the circuit breaker is open."
}
```

Response:
```json
{ "stored": true, "node_id": "method:src/replay/core/recorder.py:Recorder.add_step" }
```

**Tokens: ~52 (tool call + response)**
Summary written permanently to `replay-agent.db`. Zero LLM cost on Loom's side.

---

#### Session 1 total for this question

| Step | Tokens |
|------|--------|
| `search_code` call + response | ~433 |
| Read `recorder.py` | ~1,093 |
| `store_understanding` | ~52 |
| **Session 1 total** | **~1,578** |

---

### Session 2 — Same question, different day, different agent

Agent gets a task: *"Does add_step ever drop data silently?"*

#### Call 1 — `search_code("add_step recorder")`

Response (summary now cached):

```json
[
  {
    "id": "method:src/replay/core/recorder.py:Recorder.add_step",
    "name": "add_step",
    "path": "src/replay/core/recorder.py",
    "kind": "method",
    "line": 80,
    "summary": "Records a single LLM step into the run — computes cost, applies redaction, increments step index, and silently drops the step if the circuit breaker is open.",
    "signature": "add_step(self, *, type: StepType, ...) -> Optional[Step]"
  }
]
```

**Tokens: ~413**
Summary answers the question directly. **Agent skips the file read.**

---

#### Session 2 total for this question

| Step | Tokens |
|------|--------|
| `search_code` call + response | ~413 |
| Read `recorder.py` | **0 — skipped** |
| **Session 2 total** | **~413** |

---

### Per-function savings across sessions

```
Session 1:  1,578 tokens  (search + file read + store)
Session 2:    413 tokens  (search only — summary returned)
Session 3+:   413 tokens  (same, indefinitely)

File read eliminated from session 2 onward: saves ~1,093 tokens per question
```

The summary persists. Every future agent — in any session, any tool — gets it for free.

---

## Scale Benchmark

### replay-agent (35 source files, Python)

| Approach | Files read | Tokens |
|----------|-----------|--------|
| Read all source files | 35 | ~22,112 |
| `search_code("add_step recorder")` | 0 | ~433 |
| **Reduction** | | **98.0% — 51× fewer** |

### finpower (678 files, TS/TSX/Python/Go/JSX)

| Approach | Files read | Tokens |
|----------|-----------|--------|
| Read all source files | 678 | ~794,462 |
| `search_code("dashboard")` | 0 | ~527 |
| **Reduction** | | **99.9% — 1,507× fewer** |

---

## Index Stats

### replay-agent

```
Nodes:  400  (83 functions, 204 methods, 46 classes, 52 files, 15 communities)
Edges:  2,024  (643 calls, 112 contains, 1,269 coupled_with)
DB size: 1.6 MB
Index time: ~10s
```

### finpower

```
Nodes:  5,163  (1,526 functions, 1,005 methods, 394 classes, 756 files, 171 communities)
Edges:  11,122  (calls + contains + coupled_with)
DB size: 16 MB
Index time: ~90s
```

---

## What Makes This Different

### Every other code graph tool (Graphify, code-review-graph, ctags, Sourcegraph)

```
Session 1:  agent reads files, understands code
Session 2:  agent reads files again, understands code again
Session N:  agent reads files again
```

Static index. Read-only. Always cold.

### Loom

```
Session 1:  agent reads files, stores summaries → Loom gets smarter
Session 2:  agent gets summaries instantly → skips file reads
Session N:  compound savings, richer index
```

Write-back flywheel. The only tool that gets smarter every session.

---

## Project DB Isolation (new in this session)

Loom auto-detects the git root and creates a per-project DB:

```
~/.loom/projects/
  replay-agent.db    (1.6 MB — 400 nodes)
  finpower.db        (16 MB  — 5,163 nodes)
  loom.db            (auto when cd into this repo)

~/.loom/loom.db      (fallback — no git repo)
```

No flags. No config. `cd` into any repo and `loom analyze .` just works.
Override with `LOOM_DB_PATH` env var or `--db` flag if needed.

---

## Bugs Fixed During This Benchmark

### `_load_gitignore` recursed into `node_modules/`

`root.rglob('.gitignore')` walked into `Wren-ai/wren-ui/node_modules/` and loaded
npm package gitignore files. Those patterns matched `src/*.jsx`, causing the scanner
to find **0 files** in finpower despite JSX being a supported language.

**Fix:** replaced `rglob` with `os.walk` + dir pruning (skips `node_modules`, hidden dirs).

### Single global DB mixed all repos

All repos shared `~/.loom/loom.db` (2 GB). Cleanup passes deleted nodes from
other repos when analyzing a single repo.

**Fix:** `resolve_db_path()` derives `~/.loom/projects/{git-root-name}.db` from
`git rev-parse --show-toplevel`. Each repo gets its own isolated DB.

---

*Generated: 2026-05-01 — loom v0.3.0*
