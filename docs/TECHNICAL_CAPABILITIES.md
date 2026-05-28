# Technical Capabilities

Implementation details: parsers, metadata, edges, query internals.

---

## Code parsing

Loom parses source files into `Node` objects with file/line locations and metadata using tree-sitter.

### Parsing levels

| Level | What | Notes |
|-------|------|-------|
| **L0** | File recognition | Create FILE node for markup/config |
| **L1** | Symbol extraction | Functions, methods, classes, interfaces, enums, types |
| **L2** | Metadata extraction | Signatures, params, return types, decorators, annotations |
| **L3** | Static call edges | CALLS edges from function/method bodies |

### Language support

| Language | L1 Symbols | L2 Metadata | L3 CALLS |
|----------|------------|-------------|----------|
| Python | ✅ | ✅ | ✅ |
| TypeScript | ✅ | ✅ | ✅ |
| TSX | ✅ | ✅ | ✅ |
| JavaScript | ✅ | ✅ | ✅ |
| JSX | ✅ | ✅ | ✅ |
| Java | ✅ | ✅ | ✅ |
| Go | ✅ | ✅ | ❌ |
| Rust | ✅ | ✅ | ❌ |
| Ruby | ✅ | ✅ | ❌ |

### Markup/config (FILE nodes only)

| Format | Metadata extracted |
|--------|--------------------|
| JSON | top-level keys, type hint |
| YAML | top-level keys, type hint |
| TOML | project name/version, dependencies |
| INI | sections, key counts |
| Properties | keys, counts, sensitive key detection |
| .env | var names, sensitive key detection |
| HTML | title, forms, scripts, template hints |
| CSS | classes, ids, media queries, CSS vars |

---

## Call graph extraction

### Python

- tree-sitter call site extraction from function/method bodies
- `_extract_call_name()` assigns confidence by directness:
  - `foo()` → high confidence
  - `obj.foo()` → slightly lower
  - computed calls → unresolved
- `trace_calls()` uses `all_symbols: dict[str, list[Node]]` to avoid name collisions
- Ambiguity resolution: prefer same-file, prefer FUNCTION over METHOD for single match
- `resolve_calls()` builds a global symbol map across all files for cross-file CALLS

### TypeScript / JavaScript

- function, arrow-function, and method call extraction
- cross-file resolution heuristic

### Java

- method invocation and constructor call extraction

**Limitations:**
- cross-file resolution is heuristic, not full type-flow
- dynamic dispatch not modeled (virtual/interface calls not resolved to candidates)
- unresolved/ambiguous calls preserved with `confidence < 1.0`

---

## Index-time enrichment (v0.6.0)

### File fingerprinting

`FingerprintRepository` tracks `file_fingerprints (file_path, content_sha, mtime_ns, indexed_at)`. Incremental re-index uses mtime as a fast-path: if mtime is unchanged, the file is skipped without reading it. If mtime changed, SHA-256 is computed and compared; if identical, only mtime is updated. This gives true incremental indexing with no false re-parses.

### Complexity classification (`indexer/complexity.py`)

Cyclomatic complexity is computed from tree-sitter AST node counts (branches, loops, exception handlers, boolean operators). Result stored in `nodes.complexity` as `SIMPLE`, `MODERATE`, or `COMPLEX`.

### AutoTagger (`indexer/tagger.py`)

Post-parse pass applying three tag categories:

| Category | Examples |
|----------|---------|
| Decorator tags | `@app.route` → `api-endpoint`, `@celery.task` → `async-task`, `@login_required` → `auth` |
| Import tags | `import celery` → `async-task`, `import jwt` → `auth` |
| Directory tags | `tests/` → `test`, `migrations/` → `migration` |

Tags written to `node_tags (node_id, tag, source)` with `source="auto"`.

### TestLinker (`indexer/test_linker.py`)

Creates `TESTED_BY` edges from production code nodes to the test file/functions that cover them. Language support: Python, TypeScript, JavaScript, Java. Heuristic: test file name matches production file name (e.g. `test_auth.py` → `auth.py`).

### GraphTagger (`indexer/graph_tagger.py`)

Runs after community detection. Applies graph-topology-derived tags via `node_tags`:

| Tag | Condition |
|-----|-----------|
| `dead-code` | Function/method has 0 incoming CALLS edges |
| `entry-point` | Name matches main/handle_*/route patterns, or no incoming CALLS |
| `hub` | High in-degree (called from many modules) |
| `bridge` | Connects otherwise-separate communities |

---

## Tag system

### Storage

- `node_tags (node_id, tag, source)` — one row per tag per node
- `source` values: `"auto"` (AutoTagger/GraphTagger), `"agent"` (set via `store_understanding`)
- `nodes.tags_normalized` — space-separated string rebuilt from `node_tags` after every tag write

### Tag search (`query/search.py`)

`_TAG_RE = re.compile(r"\btag:(\S+)")` extracts `tag:X` tokens from query strings. Tag tokens are converted to `nodes_fts.tags_normalized:X` FTS5 sub-queries. Multiple `tag:` tokens are ANDed together. Non-tag terms search name/summary/path as usual.

### Agent tags

`store_understanding(node_id, summary, tags=["security-sensitive"])` writes tags with `source="agent"`. Re-index preserves `source="agent"` tags; only `source="auto"` tags are replaced on re-index.

---

## Incremental sync

Driven by SHA-256, not git.

`bulk_upsert_nodes` only bumps `updated_at` when `content_hash` changes:
```sql
updated_at = CASE
    WHEN excluded.content_hash IS NOT NULL
         AND excluded.content_hash != COALESCE(nodes.content_hash, '')
    THEN excluded.updated_at
    ELSE nodes.updated_at
END
```

This prevents false positives in delta context (re-analyzing identical files doesn't mark nodes as changed).

---

## Summary system

### Auto-summaries

`extract_summary(node)` in `analysis/code/extractor.py` builds structured text from metadata:
- signature with param types
- return type
- decorators / annotations
- framework hints

Applied as post-pass `UPDATE WHERE summary IS NULL` — never overwrites agent summaries.

Runs automatically in `index_repo()`. Coverage ~80% on first analyze.

### Agent summaries

Written via `store_understanding` MCP tool:
```sql
UPDATE nodes SET summary = ?, summary_hash = content_hash, updated_at = ? WHERE id = ?
```

`summary_hash` stores the `content_hash` at write time. If source changes later:
- `content_hash` diverges from `summary_hash`
- `get_context` returns `summary_stale: true`
- Agent re-reads source and calls `store_understanding` again

Agent summaries are preserved through re-analyze (upsert logic: `ELSE nodes.summary`).

---

## Search (FTS5)

`nodes_fts` is an FTS5 virtual table with separate columns for `name`, `summary`, `path`, `tags_normalized` (porter + unicode61 tokenizer). Triggers keep it in sync on INSERT/UPDATE/DELETE.

`search()` in `query/search.py`:
1. Extract `tag:X` tokens from query string; build FTS5 `tags_normalized:X` sub-clauses (AND)
2. Try FTS5 query against name/summary/path for remaining terms
3. Fall back to LIKE if FTS5 raises an error (malformed query)
4. Wrap results in `SearchResult(node, score)`

`search_code` MCP tool returns: `id, name, path, kind, line, score, summary, signature`.

Tag search examples: `"tag:auth login"`, `"tag:api-endpoint tag:async-task"`.

---

## Context packets

`get_context_packet()` in `graph/repository/context.py` (via `ContextRepository`) executes one DB round-trip under one lock:

1. Fetch node by ID
2. If function/method:
   - callers: `SELECT n.* FROM edges e JOIN nodes n ON n.id = e.from_id WHERE e.to_id = ? AND e.kind = 'calls'` — same-file first, by in-degree, LIMIT 10
   - callees: same pattern for `e.from_id = ?`
   - staleness: `summary_hash IS NOT NULL AND summary_hash != content_hash`
   - complexity: from `nodes.complexity` column
   - tags: from `node_tags` table for this node
   - tested_by: TESTED_BY edges pointing at this node
3. If class/file:
   - members via CONTAINS edges
4. Community: `SELECT to_id FROM edges WHERE from_id = ? AND kind = 'member_of'`

Returns ~80 tokens. Replaces 4+ separate MCP tool calls.

---

## Session primer

`build_primer()` in `query/primer.py`:
- pure SQL aggregation, no LLM, no file reads
- groups functions by module (derived from path segments, skipping `src/lib/loom/app/pkg`)
- detects entry points by name pattern (`main`, `handle_*`, `*_handler`, framework routes)
- `god_nodes` via `COUNT(edges WHERE kind='calls' AND to_id=n.id)`
- coverage: `COUNT WHERE metadata LIKE '%"signature"%'` and `COUNT WHERE summary IS NOT NULL`
- `module=` drill-down: top functions in one module, sorted by caller count

Output: ~200 tokens. MCP resource `loom://primer` for auto-load at session start.

---

## Delta context

`get_delta_payload()` in `query/delta.py`:
- `WHERE updated_at > since_ts AND deleted_at IS NULL AND kind NOT IN ('file', 'community')`
- if `changed + deleted > 100`: summary mode with top changed paths
- if within limit: full context packets for each changed node
- deleted nodes: `{id, path, change_type: "deleted"}`

Used by `get_delta` MCP tool which looks up `sessions.started_at` for the agent's last session.

---

## Community detection

`compute_communities()` in `analysis/communities.py`:
- builds NetworkX graph from CALLS edges
- runs Louvain community detection
- creates COMMUNITY nodes and MEMBER_OF edges
- runs automatically in `index_repo()`

---

## Git coupling

`compute_coupling()` in `analysis/coupling.py`:
- reads git log for co-changed files
- creates COUPLED_WITH edges between files that change together
- runs automatically in `index_repo()`

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Storage | SQLite WAL mode, FTS5 |
| Parsing | tree-sitter + tree-sitter-language-pack |
| Communities | NetworkX + python-louvain |
| MCP | FastMCP |
| CLI | Typer + Rich |
| Models | Pydantic v2 |
| Async | asyncio.to_thread() for all SQLite ops |
| Concurrency | threading.RLock per DB instance |
| Python | 3.10+ |
