# Loom

> A persistent symbol index for AI coding agents. Agents find functions instantly. Agents write summaries as they work. The cache gets richer every session — zero LLM cost from Loom's side.

## What Loom is

Loom indexes your codebase into a local SQLite database using tree-sitter. It extracts functions, classes, methods, and call relationships across all languages. Agents query it to skip file exploration and read only what they need. When an agent understands a function, it writes a summary back — the next agent gets it for free.

**Core loop:**

```
loom analyze .                    # tree-sitter indexes all symbols → ~/.loom/projects/myrepo.db
search_code("login")              # instant: {name, path, line, summary, signature}
search_code("tag:auth login")     # tag-filtered search — AND semantics
get_context(node_id)              # full picture: summary + callers + callees + complexity + tags
store_understanding(id, s)        # cache what you learned → returned on future searches
```

No Docker. No embeddings. No LLM calls from Loom. Pure tree-sitter + SQLite.

## Why it matters

Every Claude Code / Cursor / Codex session starts by re-exploring the codebase: reading CLAUDE.md, grepping for functions, re-discovering structure. Loom eliminates that.

| Repo | Files | Without Loom | With Loom | Reduction |
|------|-------|-------------|-----------|-----------|
| replay-agent | 35 Python | ~22,112 tokens | ~433 tokens | **51× fewer** |
| finpower | 678 TS/TSX/Python/Go | ~794,462 tokens | ~527 tokens | **1,507× fewer** |

- **Session 1:** agent reads files, stores summaries → Loom gets smarter
- **Session 2+:** summaries returned instantly → file reads skipped entirely
- **Compounding:** every session makes Loom richer for every future agent

## Installation

```bash
pip install loom-tool
# or with uv:
uv add loom-tool
```

Requirements: Python 3.10+. Tested on 3.10, 3.11, 3.12, 3.13, 3.14. No Docker. No external services.

### Claude Code plugin

Anyone can install directly from GitHub:

```
/plugin marketplace add ddevilz/loom
/plugin install loom@loom-tool
```

Installs the MCP server (`uvx --from loom-tool loom-mcp`) and the `/loom` skill automatically.

**Prerequisite:** [uv](https://astral.sh/uv) must be installed before the plugin can start the MCP server.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
winget install astral-sh.uv
```

**Recommended setup order:**
1. Install uv (above)
2. `/plugin marketplace add ddevilz/loom && /plugin install loom@loom-tool`
3. `loom install` — writes absolute `uvx` path into your MCP config (solves PATH issues on macOS/Linux)
4. Restart Claude Code — tools appear

## Quick start

```bash
cd loom
loom analyze .      # index the repo (~10s for 500 files)
loom install        # configure Claude Code, Cursor, Windsurf, Codex + git hook
loom serve          # start MCP stdio server
```

After `loom install`, MCP clients connect automatically. Claude Code sessions get the `loom://primer` resource loaded at startup.

## Project-isolated databases

Loom auto-detects the git root and creates a per-project database. No flags needed.

```
~/.loom/projects/
  my-api.db          ← cd ~/projects/my-api && loom analyze .
  frontend.db        ← cd ~/projects/frontend && loom analyze .
  loom.db            ← cd ~/projects/loom && loom analyze .

~/.loom/loom.db      ← fallback when not inside a git repo
```

Override with `LOOM_DB_PATH` env var or `--db` flag.

## CLI reference

| Command | Purpose |
|---------|---------|
| `loom analyze <path>` | Index or refresh the graph for a repo |
| `loom sync [--old-sha] [--new-sha]` | Incremental sync of changed files via SHA-256 |
| `loom context [-m module]` | Print ~200-token session primer (modules, hot functions, coverage) |
| `loom serve` | Start MCP stdio server |
| `loom install [--platform] [--list-plugins]` | Configure MCP for all detected AI tools + git hook |
| `loom query <text>` | FTS5 / name search across nodes |
| `loom blast-radius <target>` | Show transitive callers of a function |
| `loom callers <target>` | Direct callers (one-hop incoming CALLS) |
| `loom callees <target>` | Functions this target calls (one-hop outgoing CALLS) |
| `loom communities` | Run Louvain community detection |
| `loom dead-code` | Mark functions with no incoming CALLS |
| `loom summaries [-n N]` | Show agent-written summaries, most recent first |
| `loom savings [-n N]` | Token savings dashboard — totals + recent cache hits |
| `loom stats` | Node/edge counts by kind |
| `loom export` | Self-contained interactive HTML graph |

## MCP tools

| Tool | Purpose |
|------|---------|
| `search_code(query, limit)` | FTS5 search — returns summary + signature when cached |
| `get_context(node_id, brief?, callers_limit?, callees_limit?)` | Full context packet: summary, signature, callers, callees, staleness. Use `brief=True` for metadata-only. Use `callers_limit=0` / `callees_limit=0` to skip traversal. |
| `get_blast_radius(node_id, depth)` | Transitive callers via recursive CTE — each result includes `summary` |
| `get_neighbors(node_id, depth, limit)` | All edges, both directions — each result includes `summary` |
| `get_community(community_id, limit)` | All members of a community cluster — each result includes `summary` |
| `shortest_path(from_id, to_id)` | Shortest directed path on CALLS subgraph — each hop includes `summary` |
| `graph_stats(include_cohesion?)` | Node/edge counts by kind. `include_cohesion=True` adds per-cluster cohesion scores (0.0–1.0, < 0.2 = refactor candidate). |
| `god_nodes(limit)` | Most-called functions (highest in-degree) — each result includes `summary` |
| `store_understanding(node_id, summary, force?, tags?)` | Cache agent-generated summary permanently. Optionally attach agent tags (`tags: ["security-sensitive", "needs-refactor"]`) — persisted with `source="agent"`, survive re-index. Returns `skipped: true` if summary already fresh — no re-write needed. |
| `store_understanding_batch(updates)` | Batch version, max 50 per call |
| `get_savings()` | Token savings report — all-time totals + 10 recent hits |
| `start_session(agent_id)` | Register session start, returns session_id |
| `get_delta(previous_session_id)` | What changed since last session (changed + deleted nodes) |
| `suggest_questions(limit)` | Graph-topology investigation priorities: dead code, bridge nodes, missing summaries, low-cohesion clusters |
| `get_surprising_connections(limit)` | Non-obvious cross-module CALLS edges — returns `caller_summary` and `callee_summary` per result |
| `get_status()` | Live indexing progress + DB health |
| `get_work_plan()` | Prioritized next actions: DOCUMENT / INVESTIGATE / EXPLORE / NOTHING |

**MCP resources:**

| Resource | Purpose |
|----------|---------|
| `loom://primer` | ~200-token codebase overview — load at session start |
| `loom://savings` | Token savings report — totals + recent cache hits |

## Node ID format

`{kind}:{relative-path}:{symbol}`

```
function:src/auth.py:validate_token
method:src/models/user.py:User.save
class:src/models/user.py:User
file:src/auth.py
```

> **v0.6.1 note:** The 4-part `{kind}:{repo}:{path}:{symbol}` format is planned for a future phase. Current IDs remain 3-part.

## Agent workflow

```
# Session start — register first, then orient
start_session(agent_id="claude-code")    # store returned session_id

# Or if returning:
get_delta(previous_session_id="<id>")   # only what changed since last time

resource = read("loom://primer")         # orient: modules, hot functions, coverage
suggest_questions()                      # dead code, bridge nodes, missing summaries

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
# Returns {"ok": true, "skipped": false} — written
# Returns {"ok": true, "skipped": true}  — already fresh, no re-write needed
```

## How summaries work

**Auto-summaries:** `loom analyze` fills summaries from static metadata (params, return type, decorators) via tree-sitter. Coverage goes from 0% → ~80% on first analyze. No LLM.

**Agent summaries:** `store_understanding` stores a summary permanently with a `summary_hash` (snapshot of `content_hash` at write time).

- If source changes → `summary_stale: true` in `get_context` → agent re-reads and updates
- If source unchanged → `store_understanding` returns `skipped: true` → no duplicate writes
- Pass `force: true` to overwrite regardless
- Pass `tags: ["label", ...]` to attach agent-owned tags — these survive re-index

**Priority:** Agent summaries are never overwritten by auto-summaries. Re-analyzing preserves agent work.

## Index-time enrichment (v0.6.1)

Every `loom analyze` run now enriches the graph with additional metadata beyond raw symbols:

- **File fingerprinting** — SHA-256 + mtime stored in `file_fingerprints` table; only changed files are re-parsed (incremental by default)
- **Complexity classification** — each function/method tagged `SIMPLE`, `MODERATE`, or `COMPLEX` based on cyclomatic complexity
- **AutoTagger** — decorator tags (`api-endpoint`, `async-task`, `auth`), import tags, and directory tags applied automatically
- **TestLinker** — `TESTED_BY` edges created between test files and the production code they cover (Python, TypeScript, JavaScript, Java)
- **GraphTagger** — graph-derived tags: `dead-code`, `entry-point`, `hub`, `bridge`
- **Tag search** — `tag:X` syntax in `search_code` and `loom query`; multiple tags use AND semantics (e.g. `"tag:auth login"`)
- **Enhanced context packets** — `get_context` now returns `complexity`, `tags`, and `tested_by` fields for function/method nodes
- **Agent tags** — `store_understanding` accepts `tags: list[str]`; stored with `source="agent"` and survive re-index

## Plugin system

`loom install` uses a plugin registry. Built-in plugins: `claude-code`, `cursor`, `windsurf`, `codex`.

Add a custom platform without editing any source:

```python
# ~/.loom/plugins/zed.py
from loom.cli.plugins import Plugin, register
from pathlib import Path

register(Plugin(
    name="zed",
    config_path=Path.home() / ".config" / "zed" / "mcp.json",
    config_key="mcpServers",
))
```

```bash
loom install --list-plugins   # see all registered plugins
loom install --platform zed   # install only for Zed
```

## Session delta — how it works

```
Session 1:                     Session 2:
  start_session()                get_delta(previous_session_id)
  [work on auth.py]              → {changed: [2 fns], deleted: [], unchanged: 310}
  session_id stored              Only read the 2 changed functions. Skip the rest.
```

Delta uses `updated_at` on nodes — only bumped when `content_hash` changes. Safe against false positives from re-analyzing identical files.

## Token savings tracking

Every `search_code` hit with a cached summary records how many tokens were saved (source line count × 15 — no extra deps, no index overhead).

```bash
loom savings          # CLI dashboard
```

```
Total tokens saved: 127,400
Cache hits: 847  (agent: 23  auto: 824)
agent = store_understanding summaries (provably skipped file reads)
auto  = metadata summaries from loom analyze
```

Inside Claude Code, call `get_savings()` MCP tool or load `loom://savings` resource for the same report.

`search_code` results include `tokens_saved` and `summary_type` per hit when a summary is cached.

## Auto-indexing

When installed via the Claude Code plugin, Loom auto-indexes the current project on first session start — no manual `loom analyze` needed. If the DB is empty when the MCP server starts, indexing runs in the background while the session continues.

## Supported languages

Code extraction (functions, methods, classes, calls): **Python, TypeScript, TSX, JavaScript, JSX, Java**

Indexed as file nodes: HTML, CSS, JSON, YAML, TOML, XML, INI, .env, .properties

## Schema

Full DDL in [`src/loom/graph/schema.sql`](src/loom/graph/schema.sql). Core tables:

```sql
nodes             -- id, kind, name, path, language, summary, summary_hash,
                     token_count, content_hash, start_line, end_line, complexity,
                     tags_normalized, metadata, deleted_at, updated_at
edges             -- from_id, to_id, kind, confidence, confidence_tier
savings           -- ts, node_id, query, tokens_saved, summary_type
sessions          -- id, agent_id, started_at
meta              -- key/value counters (savings totals)
file_fingerprints -- file_path, content_sha, mtime_ns, indexed_at
node_tags         -- node_id, tag, source  (source="agent" tags survive re-index)
```

FTS5 virtual table `nodes_fts` indexes name + summary + path + tags_normalized for full-text and tag-based search.
Sessions table tracks agent session timestamps for delta context.

## Architecture

```
src/loom/
├── graph/               # Domain core (v0.6.1)
│   ├── db.py            # SQLite schema init, DB class, _add_column_if_missing
│   ├── schema.sql       # Full DDL
│   ├── models/          # Node, Edge, EdgeType, ConfidenceTier, NodeKind,
│   │                    # NodeSource, Complexity, SummarySource, QuestionType
│   └── repository/      # NodeRepository, EdgeRepository, FingerprintRepository,
│                        # TagRepository, SearchRepository, ContextRepository,
│                        # TraversalRepository, SessionRepository, AnalyticsRepository
├── indexer/             # index_repo, sync_paths, tree-sitter parsers per language
│   ├── tagger.py        # AutoTagger — decorator, import, directory tags
│   ├── test_linker.py   # TestLinker — TESTED_BY edges
│   ├── graph_tagger.py  # GraphTagger — dead-code, entry-point, hub, bridge tags
│   └── complexity.py    # Cyclomatic complexity classification
├── intelligence/        # communities (Louvain), coupling (git co-change), dead code
├── query/               # search, blast_radius, context packets, primer, delta
├── store/               # Legacy CRUD layer (backwards compat; new code uses graph/repository/)
├── server/              # FastMCP server (app.py + tools/), standalone entry point (run.py)
├── cli/                 # typer commands
│   └── plugins/         # platform plugin registry (claude-code, cursor, windsurf, codex)
├── templates/           # graph.html — interactive export UI
└── data/                # loom-skill.md — Claude Code skill installed by loom install
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

MIT - Free for personal and commercial use
