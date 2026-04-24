# Loom: Architecture Guide

High-level module overview. Not a function reference — for that, run `loom analyze .` on this repo and use `search_code`.

---

## System overview

Loom is a persistent symbol index backed by SQLite. It ingests source code via tree-sitter, stores nodes and edges, and exposes them through a CLI and MCP server.

```
flowchart:

Repository → Repo Walker → Language Parsers → Nodes + Edges
                                                    ↓
                                           SQLite (loom.db)
                                                    ↓
                     ┌──────────────────────────────┘
                     ↓                    ↓
                  CLI                 MCP Server
          (query, analyze, etc.)   (search_code, get_context, etc.)
```

No Docker. No external services. No embedding model.

---

## Package layout

```
src/loom/
├── core/
│   ├── db.py           # SQLite schema, init_schema(), _add_column_if_missing()
│   ├── node.py         # Node model (Pydantic), NodeKind, NodeSource
│   ├── edge.py         # Edge model, EdgeType enum
│   ├── context.py      # DB class (connection pool + RLock), DEFAULT_DB_PATH
│   └── content_hash.py # SHA-256 helpers
│
├── ingest/
│   ├── pipeline.py     # index_repo() — full analyze pass
│   ├── incremental.py  # sync_paths() — SHA-256-driven incremental sync
│   ├── utils.py        # sha256_of_file()
│   └── code/
│       ├── walker.py        # walk_repo() — gitignore-aware file discovery
│       ├── registry.py      # LanguageRegistry (ext → parser)
│       └── languages/       # one module per language: python.py, typescript.py, etc.
│
├── analysis/
│   ├── communities.py       # Louvain community detection (NetworkX)
│   ├── coupling.py          # git co-change analysis → COUPLED_WITH edges
│   ├── dead_code.py         # mark functions with no incoming CALLS
│   └── code/
│       ├── parser.py        # parse_code(), parse_repo()
│       ├── extractor.py     # extract_summary() — static summary from metadata
│       ├── noise_filter.py  # filter trivial nodes
│       └── calls/           # CALLS edge extraction per language
│
├── query/
│   ├── search.py            # search() — FTS5 + LIKE fallback
│   ├── traversal.py         # neighbors(), shortest_path(), stats(), god_nodes()
│   ├── blast_radius.py      # build_blast_radius_payload() — recursive CTE
│   ├── context.py           # get_context_packet() — full context in one DB round-trip
│   ├── primer.py            # build_primer() — ~200-token session overview
│   ├── delta.py             # get_delta_payload() — changed nodes since timestamp
│   └── node_lookup.py       # resolve node by name
│
├── store/
│   ├── nodes.py             # bulk_upsert_nodes(), get_node(), update_summary(),
│   │                        # mark_nodes_deleted(), prune_tombstones(), get_content_hashes()
│   └── sessions.py          # create_session(), get_session(), prune_sessions()
│
├── mcp/
│   ├── server.py            # build_server() — FastMCP, 15 tools + 1 resource
│   └── run.py               # run_stdio() — standalone entry point for uvx
│
└── cli/
    ├── _app.py              # shared typer app + callback (DB init)
    ├── ingest.py            # analyze, sync, serve, context
    ├── graph.py             # query, blast-radius, callers, callees, stats, summaries
    ├── analysis.py          # communities, dead-code
    ├── install.py           # loom install — MCP config + git hook + skill file
    └── export.py            # HTML graph export
```

---

## Data model

### `Node` (`loom.core.node`)

Every symbol and file is a `Node`.

Key fields:
- `id` — `{kind}:{path}:{symbol}`, e.g. `function:src/auth.py:validate_token`
- `kind` — `NodeKind` enum: FILE, FUNCTION, METHOD, CLASS, INTERFACE, ENUM, TYPE, COMMUNITY
- `source` — CODE (tree-sitter extracted)
- `name`, `path`, `language`
- `start_line`, `end_line`
- `metadata` — JSON dict: `{signature, params, return_type, decorators, framework_hint, ...}`
- `summary` — agent-written or auto-generated text
- `summary_hash` — `content_hash` at time summary was written (staleness detection)
- `content_hash` — SHA-256 of source line range (not whole file)
- `file_hash` — SHA-256 of whole file (used by incremental sync)
- `deleted_at` — soft-delete timestamp (set when file removed)
- `updated_at` — bumped only on `content_hash` change (not every upsert)

### `Edge` (`loom.core.edge`)

Links two nodes.

Key fields:
- `from_id`, `to_id` — node IDs
- `kind` — `EdgeType`: CALLS, CONTAINS, MEMBER_OF, COUPLED_WITH
- `confidence` — float (1.0 for tree-sitter extracted, lower for heuristic)

### Schema (`loom.core.db`)

```sql
nodes  (id, kind, name, path, language, source, summary, summary_hash,
        content_hash, file_hash, start_line, end_line, metadata,
        deleted_at, updated_at, created_at)
edges  (id, from_id, to_id, kind, confidence, metadata)
sessions (id, agent_id, started_at, node_count, summary_count)
```

FTS5 virtual table `nodes_fts` indexes `name || summary || path` for full-text search.

New columns added via `_add_column_if_missing()` (SQLite lacks `ADD COLUMN IF NOT EXISTS`).

---

## Indexing pipeline (`index_repo`)

1. `walk_repo()` discovers all files (gitignore-aware)
2. SHA-256 hash check against existing `nodes` — skip unchanged files
3. Changed files parsed in parallel (`ProcessPoolExecutor` if ≥8 files)
4. `_parse_file()` per file:
   - create FILE node
   - parse symbols via language registry
   - remap node IDs from abs path → rel path
   - extract CONTAINS edges (file → top-level symbols)
   - extract CALLS edges via language-specific call tracer
5. `resolve_calls()` — global Python symbol map for cross-file CALLS
6. `node_store.replace_file()` — atomic replace per file (delete old + bulk upsert)
7. `compute_communities()` — Louvain on CALLS graph
8. `compute_coupling()` — git co-change → COUPLED_WITH edges
9. `mark_dead_code()` — flag functions with no incoming CALLS
10. `_fill_auto_summaries()` — UPDATE nodes SET summary WHERE summary IS NULL
11. Deleted file detection — soft-delete nodes for files no longer on disk
12. `prune_tombstones()` — hard-delete soft-deleted nodes older than 30 days
13. `prune_sessions()` — keep last 20 per agent

---

## Incremental sync (`sync_paths`)

SHA-256 driven. No git required.

1. Walk repo, compute SHA-256 per file
2. Compare against stored `file_hash` in nodes
3. Re-parse only changed/added files
4. `mark_nodes_deleted()` for removed files
5. Same post-processing as `index_repo` (communities, coupling, etc.)

---

## MCP server (`build_server`)

Built with FastMCP. 15 tools, 1 resource.

All tools are async, use `asyncio.to_thread()` for SQLite, single `db._lock` per operation.

**Context packets** (`get_context`) execute one `_run()` block under one lock:
1. fetch node
2. callers (same-file first, top 10 by in-degree)
3. callees (same-file first, top 10)
4. staleness: `summary_hash != content_hash`
5. community membership

**Delta** (`get_delta`) uses `sessions.started_at` as the timestamp cutoff.
Only bumping `updated_at` on real content changes prevents false positives.

---

## Summary system

Two tiers, never conflict:

**Auto-summaries** (floor):
- `extract_summary(node)` in `analysis/code/extractor.py`
- Builds structured text from metadata: signature, params, return type, decorators
- Applied as `UPDATE nodes SET summary = ? WHERE id = ? AND summary IS NULL`
- Never overwrites agent summaries

**Agent summaries** (ceiling):
- Written via `store_understanding` MCP tool
- Sets `summary_hash = content_hash` at write time
- `summary_stale = True` when `content_hash` later changes
- Preserved through re-analyze (upsert preserves non-null summary)

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Parsing | tree-sitter + tree-sitter-language-pack |
| Storage | SQLite WAL mode, FTS5 |
| Communities | NetworkX + python-louvain |
| MCP | FastMCP |
| CLI | Typer + Rich |
| Models | Pydantic v2 |
| Async | asyncio + asyncio.to_thread() |
| Python | 3.12+ |
