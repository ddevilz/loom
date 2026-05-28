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
├── graph/                        # Domain core (v0.6.1)
│   ├── db.py                     # SQLite schema init, DB class (connection pool + RLock),
│   │                             # _add_column_if_missing(), DEFAULT_DB_PATH
│   ├── schema.sql                # Full DDL
│   ├── content_hash.py           # SHA-256 helpers
│   ├── models/
│   │   ├── node.py               # Node model (Pydantic), NodeKind, NodeSource
│   │   ├── edge.py               # Edge model, EdgeType, ConfidenceTier
│   │   └── enums.py              # Complexity, SummarySource, QuestionType
│   └── repository/
│       ├── nodes.py              # NodeRepository — bulk_upsert, get, update_summary, etc.
│       ├── edges.py              # EdgeRepository — bulk_upsert_edges()
│       ├── fingerprints.py       # FingerprintRepository — file_fingerprints table (SHA-256 + mtime)
│       ├── tags.py               # TagRepository — node_tags table, tags_normalized rebuild
│       ├── search.py             # SearchRepository — FTS5 + tag:X search
│       ├── context.py            # ContextRepository — get_context_packet() with complexity/tags/tested_by
│       ├── traversal.py          # TraversalRepository — neighbors, shortest_path, stats, god_nodes
│       ├── sessions.py           # SessionRepository — create_session, get_session, prune_sessions
│       └── analytics.py          # AnalyticsRepository — savings, delta, primer
│
├── indexer/                      # Ingestion pipeline (replaces ingest/ + parts of analysis/)
│   ├── pipeline.py               # index_repo() — full analyze pass
│   ├── incremental.py            # sync_paths() — SHA-256-driven incremental sync
│   ├── tagger.py                 # AutoTagger — decorator, import, directory tags
│   ├── test_linker.py            # TestLinker — TESTED_BY edges (Python, TS, JS, Java)
│   ├── graph_tagger.py           # GraphTagger — dead-code, entry-point, hub, bridge tags
│   ├── complexity.py             # Cyclomatic complexity classification (SIMPLE/MODERATE/COMPLEX)
│   ├── extractor.py              # extract_summary() — static summary from metadata
│   ├── walker.py                 # walk_repo() — gitignore-aware file discovery
│   ├── registry.py               # LanguageRegistry (ext → parser)
│   ├── utils.py                  # sha256_of_file()
│   ├── languages/                # one module per language: python.py, typescript.py, etc.
│   └── calls/                    # CALLS edge extraction per language
│
├── intelligence/                 # Graph analysis
│   ├── communities.py            # Louvain community detection (NetworkX)
│   ├── coupling.py               # git co-change analysis → COUPLED_WITH edges
│   ├── dead_code.py              # mark functions with no incoming CALLS
│   ├── cohesion.py               # per-cluster cohesion scores
│   ├── suggested_questions.py    # suggest_questions() — topology-derived priorities
│   └── surprising_connections.py # get_surprising_connections() — non-obvious cross-module edges
│
├── query/
│   ├── search.py                 # search() — FTS5 + tag:X + LIKE fallback
│   ├── traversal.py              # neighbors(), shortest_path(), stats(), god_nodes()
│   ├── blast_radius.py           # build_blast_radius_payload() — recursive CTE
│   ├── context.py                # get_context_packet() — full context in one DB round-trip
│   ├── primer.py                 # build_primer() — ~200-token session overview
│   ├── delta.py                  # get_delta_payload() — changed nodes since timestamp
│   └── node_lookup.py            # resolve node by name
│
├── store/                        # Legacy CRUD layer (backwards compat; new code uses graph/repository/)
│   ├── nodes.py                  # bulk_upsert_nodes(), get_node(), update_summary(), etc.
│   ├── edges.py                  # bulk_upsert_edges()
│   ├── savings.py                # record_hit(), get_savings_report()
│   └── sessions.py               # create_session(), get_session(), prune_sessions()
│
├── server/                       # MCP server (was mcp/)
│   ├── app.py                    # build_server() — FastMCP, tools + 2 resources
│   ├── run.py                    # run_stdio() — standalone entry point for uvx
│   ├── cache.py                  # In-memory context cache
│   ├── enums.py                  # Server-side enums (ErrorCode, WorkPlanPriority)
│   ├── validation.py             # Input validation helpers
│   └── tools/                   # Tool handlers: context.py, search.py, analysis.py,
│                                 #               graph.py, session.py
│
└── cli/
    ├── _app.py                   # shared typer app + callback (DB init)
    ├── ingest.py                 # analyze, sync, serve, context
    ├── graph.py                  # query, blast-radius, callers, callees, stats, summaries
    ├── analysis.py               # communities, dead-code
    ├── install.py                # loom install — MCP config + git hook + skill file
    └── export.py                 # HTML graph export
```

---

## Data model

### `Node` (`loom.graph.models.node`)

Every symbol and file is a `Node`.

Key fields:
- `id` — `{kind}:{path}:{symbol}`, e.g. `function:src/auth.py:validate_token`
- `kind` — `NodeKind` enum: FILE, FUNCTION, METHOD, CLASS, INTERFACE, ENUM, TYPE, COMMUNITY
- `source` — `NodeSource`: CODE (tree-sitter extracted)
- `name`, `path`, `language`
- `start_line`, `end_line`
- `metadata` — JSON dict: `{signature, params, return_type, decorators, framework_hint, ...}`
- `summary` — agent-written or auto-generated text
- `summary_hash` — `content_hash` at time summary was written (staleness detection)
- `content_hash` — SHA-256 of source line range (not whole file)
- `file_hash` — SHA-256 of whole file (used by incremental sync)
- `complexity` — `Complexity` enum: SIMPLE, MODERATE, COMPLEX (function/method nodes only)
- `tags_normalized` — space-separated tags string (used by FTS5 for tag-based search)
- `deleted_at` — soft-delete timestamp (set when file removed)
- `updated_at` — bumped only on `content_hash` change (not every upsert)

### `Edge` (`loom.graph.models.edge`)

Links two nodes.

Key fields:
- `from_id`, `to_id` — node IDs
- `kind` — `EdgeType`: CALLS, CONTAINS, COUPLED_WITH, TESTED_BY
- `confidence` — float (1.0 for tree-sitter extracted, lower for heuristic)
- `confidence_tier` — `ConfidenceTier` enum

### Schema (`loom.graph.db`)

```sql
nodes             (id, kind, name, path, language, source, summary, summary_hash,
                   content_hash, file_hash, file_mtime, start_line, end_line,
                   token_count, complexity, tags_normalized, is_dead_code,
                   community_id, metadata, deleted_at, updated_at)
edges             (id, from_id, to_id, kind, confidence, confidence_tier, metadata)
sessions          (id, agent_id, started_at, metadata)
savings           (id, ts, node_id, query, tokens_saved, summary_type)
meta              (key, value)        -- all-time savings counters
file_fingerprints (file_path, content_sha, mtime_ns, indexed_at)
node_tags         (node_id, tag, source)   -- source="agent" tags survive re-index
```

FTS5 virtual table `nodes_fts` indexes `name`, `summary`, `path`, `tags_normalized` as separate columns (porter + unicode61 tokenizer). Triggers keep it in sync on INSERT/UPDATE/DELETE.

New columns added via `_add_column_if_missing()` (SQLite lacks `ADD COLUMN IF NOT EXISTS`).

---

## Indexing pipeline (`index_repo`)

1. `walk_repo()` discovers all files (gitignore-aware)
2. `FingerprintRepository` — check `file_fingerprints` table (SHA-256 + mtime); skip truly unchanged files
3. Changed files parsed in parallel (`ProcessPoolExecutor` if ≥8 files)
4. `_parse_file()` per file:
   - create FILE node
   - parse symbols via language registry
   - remap node IDs from abs path → rel path
   - extract CONTAINS edges (file → top-level symbols)
   - extract CALLS edges via language-specific call tracer
5. `resolve_calls()` — global Python symbol map for cross-file CALLS
6. `node_store.replace_file()` — atomic replace per file (delete old + bulk upsert)
7. **`AutoTagger`** — apply decorator, import, and directory tags; write to `node_tags`
8. **`TestLinker`** — create `TESTED_BY` edges between test and production nodes
9. **Complexity classification** — compute SIMPLE/MODERATE/COMPLEX per function/method
10. `compute_communities()` — Louvain on CALLS graph
11. `compute_coupling()` — git co-change → COUPLED_WITH edges
12. `mark_dead_code()` — flag functions with no incoming CALLS
13. **`GraphTagger`** — apply dead-code, entry-point, hub, bridge tags based on graph topology
14. `_fill_auto_summaries()` — UPDATE nodes SET summary WHERE summary IS NULL
15. Deleted file detection — soft-delete nodes for files no longer on disk
16. `prune_tombstones()` — hard-delete soft-deleted nodes older than 30 days
17. `prune_sessions()` — keep last 20 per agent

---

## Incremental sync (`sync_paths`)

SHA-256 + mtime driven. No git required.

1. Walk repo, compute SHA-256 + mtime per file
2. Compare against `file_fingerprints` table (mtime fast-path; SHA-256 for confirmation)
3. Re-parse only changed/added files
4. `mark_nodes_deleted()` for removed files
5. Same post-processing as `index_repo` (tagger, test linker, complexity, communities, coupling, etc.)

---

## MCP server (`build_server`)

Entry point: `loom.server.run:run_stdio` (invoked as `uvx --from loom-tool loom-mcp`).

Built with FastMCP. Tools + 2 resources (`loom://primer`, `loom://savings`).

All tools are async, use `asyncio.to_thread()` for SQLite, single `db._lock` per operation.

**Context packets** (`get_context`) execute one `_run()` block under one lock:
1. fetch node
2. callers (same-file first, top 10 by in-degree)
3. callees (same-file first, top 10)
4. staleness: `summary_hash != content_hash`
5. community membership
6. complexity (from `nodes.complexity` column)
7. tags (from `node_tags` table)
8. tested_by (TESTED_BY edges for function/method nodes)

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
| Python | 3.10+ |
