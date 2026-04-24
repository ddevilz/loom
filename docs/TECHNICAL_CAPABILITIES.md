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

`nodes_fts` is an FTS5 virtual table indexing `name || summary || path`.

`search()` in `query/search.py`:
1. Try FTS5 query
2. Fall back to LIKE if FTS5 raises an error (malformed query)
3. Wrap results in `SearchResult(node, score)`

`search_code` MCP tool returns: `id, name, path, kind, line, score, summary, signature`.

---

## Context packets

`get_context_packet()` in `query/context.py` executes one DB round-trip under one lock:

1. Fetch node by ID
2. If function/method:
   - callers: `SELECT n.* FROM edges e JOIN nodes n ON n.id = e.from_id WHERE e.to_id = ? AND e.kind = 'calls'` — same-file first, by in-degree, LIMIT 10
   - callees: same pattern for `e.from_id = ?`
   - staleness: `summary_hash IS NOT NULL AND summary_hash != content_hash`
3. If class/file:
   - members via CONTAINS edges
4. Community: `SELECT to_id FROM edges WHERE from_id = ? AND kind = 'member_of'`

Returns ~80 tokens. Replaces 4 separate MCP tool calls.

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
| Python | 3.12+ |
