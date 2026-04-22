# /review-all

Full codebase review pass. Reads every module systematically, runs static analysis,
and produces one prioritized issue list. **Do NOT fix anything yet.**
The user confirms the list before any edits happen.

Work autonomously through all passes. Do not stop to ask questions unless a file is missing
or an import fails with an ambiguous error. Read the source, understand intent, then flag issues.

---

## Pass 1 — Static analysis (run first, takes <30s)

```bash
mypy src/loom/ --ignore-missing-imports 2>&1 | tee /tmp/loom-mypy.txt
ruff check src/loom/ 2>&1 | tee /tmp/loom-ruff.txt
python -c "import loom; print('import OK')" 2>&1
```

Print a summary like:
```
mypy:  42 errors across 8 files (most in: gateway.py, pipeline.py)
ruff:  17 violations (mostly unused imports)
import: OK / FAILED — <reason>
```

Do not dump every error line. Just counts + which files are worst.
The full logs are in `/tmp/` for reference during Pass 2.

---

## Pass 2 — Module review

Read each file fully. For every module, apply the review lens specific to that layer.

**Universal flags** (apply to every file):
- Silent fallback: `except Exception: return {}` or `return None` without raising — flag every occurrence
- Missing type annotations on public functions
- Top-level import of optional heavy dependency (igraph, torch, onnxruntime, etc.)
- Commented-out code blocks (delete, not comment)
- Magic strings used inline instead of constants (e.g. `"IMPLEMENTS"` scattered in code bodies)
- Functions over ~50 lines that do more than one conceptual thing

---

### 1. Core Infrastructure

#### `src/loom/config.py`
Review lens: **completeness and safety of env var handling**
- Are all env vars documented with their defaults?
- Any env var read with `os.environ["X"]` (raises) vs `os.getenv("X")` (silent None)?
  Flag mismatches — sensitive vars (API keys, DB URLs) should fail loud if missing.
- Are FalkorDB connection params (host, port, password) all sourced here, or scattered?

#### `src/loom/__init__.py`
Review lens: **public API surface**
- Does it export what it claims to export?
- Any wildcard imports (`from x import *`) that pollute the namespace?
- Version string present and matches pyproject.toml?

#### `src/loom/core/protocols.py`
Review lens: **interface completeness**
- Do all protocols define the full contract that implementations must satisfy?
- Are there methods on concrete classes that should be on the protocol instead?
- Any protocol method with a default implementation — should it have one?

#### `src/loom/core/node.py`
Review lens: **data model correctness**
- Are all node types represented? (Symbol, DocNode, File — at minimum)
- Do enum values match what's used in Cypher queries in `cypher.py`?
- Every node should have: `file`, `name`, `id`. Flag any that can be `None` silently.
- Any optional field that would silently produce orphaned nodes if `None`?

#### `src/loom/core/edge.py`
Review lens: **edge type consistency**
- Are all edge types defined here as constants/enum?
  Required: `CALLS`, `IMPLEMENTS`, `SPECIFIES`, `VIOLATES`, `DEPENDS_ON`
- Cross-check: any edge type string in `cypher.py`, `linker.py`, or `blast_radius.py`
  that is NOT defined here? Every raw `"IMPLEMENTS"` string in a non-edge file is a violation.
- Is the direction convention documented? `(source)-[:CALLS]->(target)` = source calls target.

#### `src/loom/core/content_hash.py`
Review lens: **hash stability**
- Is the hash deterministic across platforms (line endings, encoding)?
- Does it hash the whole file or just sections? Document which.
- Is it used as a cache key anywhere? If so, changing the algorithm silently invalidates
  all cached data — flag if unversioned.

#### `src/loom/core/graph.py`
Review lens: **state management and single source of truth**
- Is `LoomGraph` the single source of truth, or do other modules hold their own FalkorDB
  references that can drift out of sync?
- Are write operations transactional or fire-and-forget?
- Does any write method return `None` on failure instead of raising?
- Is the graph name (e.g. `loom_repo`) validated before use, or can a typo silently create
  a new empty graph?

#### `src/loom/core/falkor/gateway.py`
Review lens: **connection lifecycle and error surfacing**
- Is the connection created once and reused, or re-created per call?
- Do connection errors propagate up, or get swallowed into `return None`?
- Is there a health check / reconnect path? If FalkorDB restarts, does Loom recover or hang?
- Thread safety: if multiple ingest workers run concurrently, is the gateway safe?

#### `src/loom/core/falkor/schema.py`
Review lens: **schema migration safety**
- What happens if the schema already exists and `initialize()` is called again?
  Must be idempotent, not error or silently drop data.
- Are indexes created for fields used in `WHERE` clauses? (`symbol.name`, `node.file`, etc.)
- Any schema change here that would silently break existing graphs without a migration?

#### `src/loom/core/falkor/mappers.py`
Review lens: **serialization round-trip correctness**
- Does every field on `Node`/`Edge` dataclasses have a corresponding mapper entry?
- Null handling: what happens when an optional field is `None`? Stored as null, empty string, or omitted?
- Round-trip correctness: `db_row → Node → db_row` should produce identical output.
  Flag any lossy conversion.

#### `src/loom/core/falkor/cypher.py`
Review lens: **query correctness and injection safety**
- Are query parameters passed as parameterized variables, or string-interpolated?
  `f"MATCH (n {{name: '{name}'}})"`  ← injection risk, CRITICAL
  `g.query("MATCH (n {name: $name})", {"name": name})` ← correct
- Any query doing a full scan (`MATCH (n) RETURN n`) without a `LIMIT`?
  Will destroy performance as graph grows. Flag every unbounded scan.
- **BFS direction check:** Any query that traverses `CALLS` edges — does it use
  `-[:CALLS]->` (outgoing = callees) or `<-[:CALLS]-` (incoming = callers)?
  **Blast radius MUST use `<-[:CALLS]-` — flag any blast-radius query using outgoing direction.**

#### `src/loom/core/falkor/edge_type_adapter.py`
Review lens: **serialization completeness**
- Does it handle every edge type defined in `edge.py`?
- What happens with an unknown edge type — raises or silently drops?
- Is it bidirectional (serialize AND deserialize)?

#### `src/loom/core/falkor/repositories.py`
Review lens: **query correctness and lazy imports**
- `import igraph` — must NOT be at the top level. **BUG-3: if present at top level, CRITICAL.**
  Must only appear inside `_rank_by_personalized_pagerank()`.
- PageRank: if igraph is not installed, should raise `ImportError` with a clear message,
  not a cryptic `NameError`.
- Are there repeated `MATCH (n)` patterns that should be extracted to named query functions?

---

### 2. CLI Interface

#### `src/loom/cli.py`
Review lens: **flag wiring and user-facing correctness**
- `loom serve --host` / `--port`: are these flags actually passed to `mcp.run()`?
  If `mcp.run(transport="stdio")` is called and ignores them, that is **BUG-2 — CRITICAL.**
- `loom analyze` / `loom index`: do `--jira-*` flags pass all the way down to
  `integrations/jira.py`, or get dropped somewhere in the call chain?
  Trace the full call path: `cli.py → pipeline.py → jira.py`. Flag any gap.
- Any command that prints success but silently did nothing (e.g. indexing 0 files without warning)?
- Is `--force` wired through to `incremental.py` to trigger full re-index?

---

### 3. Code Analysis & Parsing

#### `src/loom/analysis/code/parser.py`
Review lens: **AST coverage and error handling**
- Does it handle parse errors gracefully (malformed files)?
  Should log + skip, never crash the entire pipeline.
- Does it produce consistent `Symbol` nodes with all required fields populated?

#### `src/loom/analysis/code/extractor.py`
Review lens: **extraction completeness**
- Does it extract docstrings from all relevant node types (functions, classes, modules)?
- Is extracted text sanitized (no trailing whitespace, consistent encoding)?

#### `src/loom/analysis/code/calls.py`
Review lens: **dispatch correctness**
- Is this the router to `calls_ts.py`, `calls_java.py`, etc.?
- For an unrecognized extension, does it return `[]` silently or log a warning?
  Silent empty return = silently missing CALLS edges. Should warn.

#### `src/loom/analysis/code/calls_ts.py` and `calls_java.py`
Review lens: **call edge direction correctness**
- Does it produce `(caller)-[:CALLS]->(callee)` edges with the correct direction?
- Does it handle dynamic calls by skipping (not crashing)?

#### `src/loom/ingest/code/registry.py`
Review lens: **language registration completeness — BUG-1 is here**
- **BUG-1 CRITICAL CHECK:** Do `EXT_JS` and `EXT_JSX` have `call_tracer=trace_calls_for_ts_file`?
  If either has `call_tracer=None`, flag CRITICAL immediately.
- Are all languages registered as a consistent pair (parser + call_tracer)?
- Is there an explicit fallback for unknown extensions, or silent skip?

#### Language files: `python.py`, `typescript.py`, `javascript.py`, `java.py`, `go_lang.py`, `rust.py`, `ruby.py`, `markup.py`
Review lens: **cross-language interface consistency**
- Do all language modules expose the same interface?
- Does each define BOTH a parser AND a call tracer?
  Missing tracer = no CALLS edges for that language = silent graph incompleteness.
- `markup.py`: should produce `DocNode`, not `Symbol` — verify node type is correct.

#### `src/loom/ingest/code/languages/_ts_utils.py` and `constants.py`
Review lens: **shared utility scope**
- Are TS utilities imported only by TS/JS files, or accidentally leaking to other languages?
- Are constants used everywhere they apply, or are some callsites still using raw strings?

---

### 4. Document Processing

#### `src/loom/ingest/docs/base.py`, `markdown.py`, `pdf.py`
Review lens: **DocNode production correctness**
- Does each produce `DocNode` with all required fields (`name`, `file`, `content`, `id`)?
- PDF: does it handle scanned/image-only PDFs (no text extractable) gracefully?
- Markdown: does it segment by heading? A 500-line README should produce multiple DocNodes,
  not one giant node — one giant node defeats semantic linking.
- Are doc nodes linked to their source file via a `DEPENDS_ON` or `SPECIFIES` edge?

---

### 5. Ingestion Pipeline

#### `src/loom/ingest/pipeline.py`
Review lens: **pipeline correctness and error propagation**
- Does a parse error on one file stop the entire pipeline, or skip and continue?
  Should always skip + log. Never crash the whole run.
- Is the pipeline idempotent? Running it twice should produce identical graph state.
- Does it report progress (files processed, nodes created, edges created)?

#### `src/loom/ingest/incremental.py`
Review lens: **hash miss handling — BUG-3 adjacent, silent fallback is the enemy**
- On a hash miss (file changed): does it re-index correctly, or silently reuse stale data?
  **Must raise or re-index. Never silently reuse stale data.**
- Is the `--force` flag respected? Should trigger full re-index, not incremental diff.

#### `src/loom/ingest/differ.py`
Review lens: **change detection accuracy**
- Does it correctly identify added, modified, and deleted files?
- Renamed files: are old nodes cleaned up from the graph, or left as orphans?

#### `src/loom/ingest/git.py`
Review lens: **read-only safety**
- Are all git operations read-only? Flag any that could mutate state.
- Does it handle non-git directories gracefully?

#### `src/loom/ingest/integrations/jira.py`
Review lens: **auth validation, error surfacing, data quality, deduplication**
- Does it validate the Jira token BEFORE starting the index run?
  A 401 after 5 minutes of indexing is a terrible user experience.
- Are Jira API errors (4xx, 5xx) raised with the response body, or silently swallowed?
- What gets written to Jira? Issues must contain: symbol name, file path, description.
  Vague issues like "potential issue in file X" are useless.
- **Deduplication:** running `loom analyze` twice must not create duplicate Jira issues.
  Is there a check for existing issues before creating new ones?
- Is `--jira-project` validated against the Jira API before writing, or does a typo
  silently fail mid-run with a cryptic 404?

---

### 6. Semantic Linking

#### `src/loom/linker/linker.py`
Review lens: **orchestration correctness**
- Does it call all three matchers (embed, name, llm) and merge results?
- Are duplicate edges prevented? Two matchers might independently produce the same
  `(A)-[:IMPLEMENTS]->(B)` — only one edge should be created.
- Does it handle an empty graph (no symbols, no doc nodes) without crashing?

#### `src/loom/linker/embed_match.py`
Review lens: **similarity threshold and batching**
- Is the similarity threshold configurable or hardcoded? Should be in `config.py`.
- Is the embedding model called per-symbol or per-batch?
  **Per-symbol is a critical performance problem at scale.** Flag if present.

#### `src/loom/linker/llm_match.py`
Review lens: **LLM call safety and cost control**
- Are LLM calls bounded by a timeout? A hanging LLM must not hang the pipeline.
- Is there a per-run limit? LLM matching on a large codebase could cost $100+ without a cap.
- Is the LLM response validated before creating edges? The LLM could hallucinate an edge type.

#### `src/loom/linker/reranker.py`
Review lens: **reranking result handling**
- Are edges below threshold after reranking dropped or kept?
- Does it operate across all matcher outputs combined, or per-matcher in isolation?

---

### 7. Embeddings

#### `src/loom/embed/embedder.py`
Review lens: **batching, config, and caching**
- Is embedding done in batches? One-by-one is ~100x slower — flag if present.
- Is the model name a constant from `config.py`, or a hardcoded string?
- Are embeddings cached? Re-embedding unchanged symbols on every run is wasteful.
- What happens if the model is not downloaded — clear error or cryptic crash?

---

### 8. Query Engine

#### `src/loom/query/blast_radius.py`
Review lens: **BFS direction — the single most critical correctness check in Loom**
- **CRITICAL:** Does the BFS traverse `<-[:CALLS]-` (incoming = who calls the target)?
  It MUST follow callers, not callees. Callees = dependency tree. Callers = impact tree.
  These are OPPOSITE meanings. Wrong direction = every blast radius result is wrong.
- Is there a depth limit? Unbounded BFS on a large graph will hang indefinitely.
- Are results deduplicated? A symbol reachable via multiple paths should appear once.

#### `src/loom/query/node_lookup.py`
Review lens: **resolution correctness**
- Does it handle ambiguous symbol names (same function name in multiple files)?
- Does it return `None` silently or raise when a symbol is not found?

#### `src/loom/query/traceability.py`
Review lens: **bidirectional coverage**
- Can you query both directions:
  "which specs does this function implement?" AND "which functions implement this spec?"
- Are `VIOLATES` edges included in results with a distinct status label?

---

### 9. Search

#### `src/loom/search/searcher.py`
Review lens: **search completeness**
- Does it search both `Symbol` and `DocNode`, or only one type?
- Is the similarity threshold exposed or hardcoded?
- Are results ranked by score descending?

---

### 10. Drift Detection

#### `src/loom/drift/detector.py`
Review lens: **detection accuracy and output shape**
- Does it compare the current AST against the indexed snapshot correctly?
- Does it report drifted symbols with file and line number?
- **BUG-4 check:** Does anything here (or the MCP tool that calls it) produce
  `semantic_violations: []` as a vestigial key? If yes, flag CRITICAL.

---

### 11. MCP Server

#### `src/loom/mcp/server.py`
Review lens: **tool correctness, response shape, no misleading output**
- **BUG-2 check:** `mcp.run(transport="stdio")` while `--host`/`--port` flags are advertised?
  Flag CRITICAL if present.
- **BUG-4 check:** Does `check_drift` response contain `"semantic_violations": []`?
  Flag CRITICAL if present.
- Is error handling consistent? Every tool must either return a valid result or raise.
  Never `{"error": None}` or `{"result": null}`.
- Is there repeated error-formatting boilerplate across tool handlers?
  Should be a single `_tool_error(name, exc)` helper.
- Are tool docstrings accurate and specific? The docstring IS the tool description seen
  by LLMs — vague descriptions cause wrong tool selection by agents.

---

### 12. File Watching

#### `src/loom/watch/watcher.py`
Review lens: **event debouncing and error recovery**
- Does it debounce rapid file changes (a save that triggers 3 events in 100ms)?
- Does it handle file deletion by removing nodes from the graph?
- On error: does it stop silently or log and continue watching?

---

### 13. LLM Integration

#### `src/loom/llm/base.py` and `lite_llm.py`
Review lens: **error handling and configurability**
- Are LLM errors (rate limit, timeout, bad response) raised explicitly or swallowed?
- Is the model name configurable via `config.py`, or hardcoded?
- Is there a retry policy? One-shot LLM calls fail in production.

---

## Pass 3 — Cross-module repetition audit

After reading all files, answer these questions explicitly:

**FalkorDB client access:**
How many different places create or access a FalkorDB connection?
Should be exactly one: `gateway.py`. If `pipeline.py`, `repositories.py`, `server.py`,
or any other module creates its own connection, flag all callsites as DRY violations.

**Error response formatting in MCP:**
How many tools in `server.py` construct their own error dict inline?
Should be one `_tool_error(name, exc)` helper. Count the violations.

**Node/Edge dict construction:**
Are `{"type": "...", "name": "...", "file": "..."}` dicts built outside `mappers.py`?
Every node/edge construction should go through mappers.

**Embedding calls:**
How many places call into the embedding model directly vs going through `embedder.py`?
Should be exactly one entry point.

**Edge type strings:**
How many files contain raw strings like `"IMPLEMENTS"`, `"CALLS"`, `"SPECIFIES"`?
If more than one file uses them as raw strings, they must be moved to `edge.py` constants.

**Cypher MATCH patterns:**
Are `MATCH (s:Symbol {name: $name})` patterns repeated across `cypher.py` and
`repositories.py`? Should be named query functions, not repeated inline Cypher.

---

## Output format

After all passes, produce one prioritized list:

```
## CRITICAL — breaks correctness (fix before anything else)
- [src/loom/path/file.py:LINE] WHAT is wrong — WHY it breaks correctness

## DRY VIOLATIONS — repeated logic to extract
- [src/loom/path/file.py:LINE] WHAT is duplicated — WHERE it should be extracted to

## MISLEADING — outputs or behaviors that lie to the caller/user
- [src/loom/path/file.py:LINE] WHAT is misleading — WHAT the correct behavior should be

## CLEANUP — dead code, unused imports, missing types, minor issues
- [src/loom/path/file.py:LINE] WHAT to clean up
```

After the list, print and add all of them in the ISSUES.md file:

```
Total: X critical, X DRY violations, X misleading, X cleanup items
mypy errors resolved by fixing critical items: ~X
```

Then ask: "Which issues do you want to fix first? I'll do them one at a time with tests."