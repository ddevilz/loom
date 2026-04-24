# Loom

> A persistent symbol index for AI coding agents. Agents find functions instantly. Agents write summaries as they work. The cache gets richer every session — zero LLM cost from Loom's side.

## What Loom is

Loom indexes your codebase into a local SQLite database using tree-sitter. It extracts functions, classes, methods, and call relationships across all languages. Agents query it to skip file exploration and read only what they need. When an agent understands a function, it writes a summary back — the next agent gets it for free.

**Core loop:**

```
loom analyze .              # tree-sitter indexes all symbols → ~/.loom/loom.db
search_code("login")        # instant: {name, path, line, summary, signature}
get_context(node_id)        # full picture: summary + callers + callees, one call
store_understanding(id, s)  # cache what you learned → returned on future searches
```

No Docker. No embeddings. No LLM calls from Loom. Pure tree-sitter + SQLite.

## Why it matters

Every Claude Code / Cursor / Codex session starts by re-exploring the codebase: reading CLAUDE.md, grepping for functions, re-discovering structure. Loom eliminates that.

- **First session:** 8× token savings — summaries replace file reads
- **Session 2+:** 90×+ savings — delta context shows only what changed
- **Compounding:** every agent run makes Loom smarter for the next

## Installation

```bash
pip install loom-tool
# or with uv:
uv add loom-tool
```

Requirements: Python 3.12+. No Docker. No external services.

## Quick start

```bash
cd my-repo
loom analyze .      # index the repo (~10s for 500 files)
loom install        # configure Claude Code, Cursor, Windsurf, Codex + git hook
loom serve          # start MCP stdio server
```

After `loom install`, MCP clients connect automatically. Claude Code sessions get the `loom://primer` resource loaded at startup.

## CLI reference

| Command | Purpose |
|---------|---------|
| `loom analyze <path>` | Index or refresh the graph for a repo |
| `loom sync [--old-sha] [--new-sha]` | Incremental sync of changed files via SHA-256 |
| `loom context [-m module]` | Print ~200-token session primer (modules, hot functions, coverage) |
| `loom serve` | Start MCP stdio server |
| `loom install [--platform]` | Configure MCP for all detected AI tools + git hook |
| `loom query <text>` | FTS5 / name search across nodes |
| `loom blast-radius <target>` | Show transitive callers of a function |
| `loom callers <target>` | Direct callers (one-hop incoming CALLS) |
| `loom callees <target>` | Functions this target calls (one-hop outgoing CALLS) |
| `loom communities` | Run Louvain community detection |
| `loom dead-code` | Mark functions with no incoming CALLS |
| `loom summaries [-n N]` | Show agent-written summaries, most recent first |
| `loom stats` | Node/edge counts by kind |
| `loom export` | Self-contained interactive HTML graph |

## MCP tools

Agents use these tools directly when Loom is connected via MCP:

| Tool | Purpose |
|------|---------|
| `search_code(query, limit)` | FTS5 search — returns summary + signature when cached |
| `get_node(node_id)` | Single node by id |
| `get_context(node_id)` | Full context packet: summary, signature, callers, callees, staleness |
| `get_callers(node_id)` | One-hop incoming CALLS |
| `get_callees(node_id)` | One-hop outgoing CALLS |
| `get_blast_radius(node_id, depth)` | Transitive callers via recursive CTE |
| `get_neighbors(node_id, depth)` | All edges, both directions |
| `get_community(community_id)` | All members of a community cluster |
| `shortest_path(from_id, to_id)` | Shortest directed path on CALLS subgraph |
| `graph_stats()` | Node/edge counts by kind |
| `god_nodes(limit)` | Most-called functions (highest in-degree) |
| `store_understanding(node_id, summary)` | Cache agent-generated summary permanently |
| `store_understanding_batch(updates)` | Batch version, max 50 per call |
| `start_session(agent_id)` | Register session start, returns session_id |
| `get_delta(previous_session_id)` | What changed since last session (changed + deleted nodes) |

**MCP resource:**

| Resource | Purpose |
|----------|---------|
| `loom://primer` | ~200-token codebase overview — load at session start |

## Node ID format

`{kind}:{relative-path}:{symbol}`

```
function:src/auth.py:validate_token
method:src/models/user.py:User.save
class:src/models/user.py:User
file:src/auth.py
```

## Agent workflow

```
# Session start
resource = read("loom://primer")         # orient: modules, hot functions, coverage
start_session(agent_id="claude-code")    # store returned session_id

# Or if returning:
get_delta(previous_session_id="<id>")   # only what changed since last time

# Finding code
results = search_code("validate token") # summary + signature included
# If results[0].summary → read summary, skip file

# Before reading any file
ctx = get_context("function:src/auth.py:validate_token")
# Returns callers, callees, summary, staleness — often enough to reason without reading

# After understanding a function
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature invalid."
)
```

## Session delta — how it works

```
Session 1:                     Session 2:
  start_session()                get_delta(previous_session_id)
  [work on auth.py]              → {changed: [2 fns], deleted: [], unchanged: 310}
  session_id stored              Only read the 2 changed functions. Skip the rest.
```

Delta uses `updated_at` on nodes — only bumped when `content_hash` changes. Safe against false positives from re-analyzing identical files.

## Supported languages

Code extraction (functions, methods, classes, calls): Python, TypeScript, TSX, JavaScript, JSX, Java, Go, Rust, Ruby

Indexed as file nodes: HTML, CSS, JSON, YAML, TOML, XML, INI, .env, .properties

## How summaries work

**Auto-summaries:** `loom analyze` fills summaries from static metadata (params, return type, decorators) via tree-sitter. Coverage goes from 0% → ~80% on first analyze. No LLM.

**Agent summaries:** `store_understanding` stores a summary permanently with a `summary_hash` (snapshot of `content_hash` at write time). If source changes later, `summary_stale: true` appears in `get_context` — agent knows to re-read and update.

**Priority:** Agent summaries are never overwritten by auto-summaries. Re-analyzing the same file preserves agent work.

## Schema

Two core tables in `~/.loom/loom.db`:

```sql
nodes  -- id, kind, name, path, language, summary, summary_hash,
          content_hash, start_line, end_line, metadata, deleted_at, updated_at
edges  -- from_id, to_id, kind, confidence
```

FTS5 virtual table `nodes_fts` indexes name + summary + path for full-text search.

Sessions table tracks agent session timestamps for delta context.

## Architecture

```
src/loom/
├── core/          # Node/Edge models, DB context, schema (db.py)
├── ingest/        # index_repo, sync_paths, tree-sitter parsers per language
├── analysis/      # communities (Louvain), coupling (git co-change), dead code
├── query/         # search, blast_radius, context packets, primer, delta
├── store/         # nodes CRUD, sessions, FTS5 sync
├── mcp/           # FastMCP server (server.py), standalone entry point (run.py)
└── cli/           # typer commands
```

## Development

```bash
git clone https://github.com/ddevilz/loom
cd loom
uv sync
uv run pytest
uv run ruff check .
uv run mypy src/
```

## License

MIT
