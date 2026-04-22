# Loom — Simplification Migration

**Goal:** Strip Loom down to its defensible core. Remove all infrastructure that
doesn't directly serve the call graph, blast radius, and MCP server. The end state
is a tool that works with `pip install loom-tool` and zero Docker.

**Reference projects studied:**
- `safishamsi/graphify` — NetworkX + tree-sitter, no server, 71.5× token reduction
- `tirth8205/code-review-graph` — SQLite + NetworkX, SHA-256 incremental, MCP, 8.2× reduction

---

## What changes and why

### 1. Replace FalkorDB with SQLite + NetworkX

**Remove entirely:**
```
src/loom/core/falkor/
  gateway.py       # FalkorDB connection, singleton, reconnect logic
  repositories.py  # NodeRepository, EdgeRepository, TraversalRepository
  schema.py        # DDL init, index creation, thread locks
  cypher.py        # All Cypher query strings
  mappers.py       # Serialize/deserialize node/edge props
  edge_type_adapter.py  # EdgeType ↔ uppercase storage name
docker-compose.yml
```

**Replace with:**
```
src/loom/core/graph.py  # Rewrite using sqlite3 (stdlib) + networkx
```

**New schema — two tables only:**
```sql
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    source       TEXT NOT NULL,
    name         TEXT NOT NULL,
    path         TEXT NOT NULL,
    start_line   INTEGER,
    end_line     INTEGER,
    language     TEXT,
    content_hash TEXT,
    summary      TEXT,
    metadata     TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);

CREATE TABLE IF NOT EXISTS edges (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    TEXT NOT NULL,
    to_id      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    origin     TEXT DEFAULT 'computed',
    metadata   TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_edges_from    ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to      ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind    ON edges(kind);
CREATE INDEX IF NOT EXISTS idx_edges_to_kind ON edges(to_id, kind);
```

**SQLite connection settings to always apply:**
```python
conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads
conn.execute("PRAGMA synchronous=NORMAL") # safe but faster writes
```

**Blast radius implementation — load only CALLS subgraph into NetworkX:**
```python
def blast_radius(self, node_id: str, depth: int = 3) -> list[Node]:
    # Load only CALLS edges into NetworkX — not the whole graph
    edge_rows = conn.execute(
        "SELECT from_id, to_id FROM edges WHERE kind = 'calls'"
    ).fetchall()
    g = nx.DiGraph()
    for row in edge_rows:
        g.add_edge(row["from_id"], row["to_id"])

    # BFS over predecessors (who calls this node, transitively?)
    visited: dict[str, int] = {}
    frontier = {node_id}
    for d in range(1, depth + 1):
        next_frontier: set[str] = set()
        for nid in frontier:
            for pred in g.predecessors(nid):
                if pred not in visited and pred != node_id:
                    visited[pred] = d
                    next_frontier.add(pred)
        frontier = next_frontier
        if not frontier:
            break

    # Fetch full node data only for the result set
    if not visited:
        return []
    placeholders = ",".join("?" * len(visited))
    rows = conn.execute(
        f"SELECT * FROM nodes WHERE id IN ({placeholders})",
        list(visited.keys()),
    ).fetchall()
    result = [_row_to_node(r) for r in rows]
    for node in result:
        node.depth = visited.get(node.id)
    return sorted(result, key=lambda n: n.depth or 0)
```

**Why not DuckDB or kuzu:**
- DuckDB is columnar/analytical — graph BFS in recursive CTEs is awkward
- kuzu is purpose-built but newer (~2022), adds a binary dep, smaller community
- SQLite is stdlib, zero install, universally understood, fast enough to 50K nodes

---

### 2. Remove the entire embedding pipeline

**Remove entirely:**
```
src/loom/embed/
  embedder.py      # FastEmbedder, InfinityEmbedder, CachedEmbedder, embed_nodes()
```

**Remove from pyproject.toml:**
```toml
# DELETE these lines:
"fastembed>=0.7.4",
"sentence-transformers>=3.0.1",
"infinity-emb[optimum]>=0.0.45",
"diskcache>=5.6",
```

**Remove from config.py:**
```python
# DELETE these config vars:
LOOM_EMBED_ENABLED
LOOM_EMBED_MODEL
LOOM_EMBED_DIM
LOOM_EMBED_BATCH_SIZE
LOOM_EMBED_CACHE_DIR
LOOM_EMBED_BACKEND
LOOM_EMBED_CACHE_SIZE_GB
```

**Why:** Graphify proves you don't need a separate embedding model for code
knowledge graphs. Community detection works from graph topology alone (edge
density via Leiden). Blast radius works from explicit CALLS edges. The
embedding pipeline added ~3 minutes to first-run install time and made
`loom analyze` require model download before first use.

**What replaces search:** Name-prefix search over SQLite is sufficient for the
current use cases. Add optional semantic search back in v0.3 if users ask.

---

### 3. Remove the semantic linker

**Remove entirely:**
```
src/loom/linker/
  linker.py        # SemanticLinker — depended on embedding pipeline
  embed_match.py   # link_by_embedding — depended on embedding pipeline
  ticket_linker.py # TicketLinker — depended on embedding pipeline
```

**Downstream:** Remove all calls to `SemanticLinker().link(...)` in:
- `src/loom/ingest/pipeline.py` — `_link_code_nodes()` function, delete it
- `src/loom/ingest/incremental.py` — `_finalize_upsert_nodes()`, remove linker call
- `src/loom/cli/ingest.py` — `relink` command, delete it

---

### 4. Remove the drift detector

**Remove entirely:**
```
src/loom/drift/
  detector.py      # detect_violations(), detect_ast_drift(), ViolationReport
```

**Downstream:** Remove drift detection calls in:
- `src/loom/ingest/incremental.py` — `_sync_modified_path()`, remove drift block
- `src/loom/mcp/server.py` — `check_drift` tool, remove it

**Why:** LLM-based violation detection requires an API call per code→doc pair.
Adds cost, adds latency, adds complexity. `LOOM_VIOLATES` edges are removed
from the EdgeType enum (or kept dormant for future use).

---

### 5. Remove external ticket connectors

**Remove entirely:**
```
src/loom/ingest/integrations/
  jira.py          # JiraConfig, fetch_jira_nodes()
  __init__.py

src/loom/ingest/connectors/
  github_issues.py # GitHubConnector, GitHubConfig
  base.py          # TicketConnector, TicketFetchResult
  __init__.py

src/loom/ingest/git_linker.py   # link_commits_to_tickets()
src/loom/ingest/git_miner.py    # mine_repo(), CommitRef, MiningResult
src/loom/linker/ticket_linker.py # already removed above
src/loom/mcp/tools/tickets.py   # MCP ticket tools
```

**Remove from pyproject.toml:**
```toml
# DELETE:
"tqdm>=4.66.0",    # only used by Jira/GitHub pagination progress bars
```

**Remove from config.py:**
```python
# DELETE:
LOOM_JIRA_URL
LOOM_JIRA_EMAIL
LOOM_JIRA_API_TOKEN
validate_jira_config()
```

**Why:** Jira and GitHub integrations are a separate product surface. They
added 3 files of connector code, a git mining pipeline, ticket-to-code linker,
5 MCP tools, and 3 config vars — none of which help the core call graph use case.
Ship v0.2 without them. Add back as an optional plugin after Show HN.

---

### 6. Remove the file watcher

**Remove entirely:**
```
src/loom/watch/
  watcher.py       # watch_repo(), uses watchfiles
```

**Remove from pyproject.toml:**
```toml
# DELETE:
"watchfiles>=1.1.1",
```

**Remove from cli/ingest.py:** The `watch` command.

**Replace with a git post-commit hook (3 lines):**
```bash
#!/bin/sh
# .git/hooks/post-commit
loom sync \
  --old-sha "$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD)" \
  --new-sha "$(git rev-parse HEAD)"
```

Install via `loom setup --hook` which writes this file and `chmod +x`s it.
This is exactly what code-review-graph does. No background process, no
watchfiles dependency, no asyncio event loop sitting idle.

---

### 7. Simplify community detection

**Keep** `src/loom/analysis/code/communities.py` but remove the igraph/leidenalg
dependency and replace with `networkx.algorithms.community`:

```python
# Remove from pyproject.toml:
"igraph>=1.0.0",
"leidenalg>=0.11.0",

# Add:
"networkx>=3.3",  # already needed for blast radius
```

```python
# Replace leidenalg.find_partition() with:
import networkx.algorithms.community as nx_comm

communities = nx_comm.louvain_communities(g_undirected, weight="weight")
```

Louvain is NetworkX's built-in community detection. It's not identical to
Leiden but produces comparable results for code graphs and removes two C
extension dependencies.

**If Leiden quality matters later:** Add `graspologic` as an optional dep
(what graphify uses). Don't add it now.

---

### 8. Simplify the MCP server

**Remove from `src/loom/mcp/server.py`:**
- `check_drift` tool — drift detection removed
- `get_impact` tool — ticket integration removed
- `get_ticket` tool — ticket integration removed
- `unimplemented` tool — ticket integration removed
- `relink` tool — semantic linker removed

**Keep:**
- `search_code` — name search, rewrite to use SQLite LIKE
- `get_callers` — one-hop CALLS, direct SQL
- `get_blast_radius` — multi-hop CALLS, NetworkX BFS
- `get_spec` — keep if Jira nodes still in schema (graceful empty result if none)

**Rewrite `search_code` without embeddings:**
```python
@mcp.tool()
async def search_code(query: str, limit: int = 10) -> list[dict]:
    """Search for functions, classes, and methods by name."""
    results = graph.search_by_name(query, limit=limit)
    return [{"id": r.id, "name": r.name, "path": r.path, "kind": r.kind.value}
            for r in results]
```

---

## pyproject.toml — before and after

**Remove these dependencies:**
```toml
"falkordb>=1.6.0",
"fastembed>=0.7.4",
"sentence-transformers>=3.0.1",
"infinity-emb[optimum]>=0.0.45",
"diskcache>=5.6",
"watchfiles>=1.1.1",
"tqdm>=4.66.0",
"igraph>=1.0.0",
"leidenalg>=0.11.0",
"uvloop ; sys_platform != 'win32'",   # only needed if running async server
"winloop>=0.5.0; platform_system == 'Windows'",
```

**Add:**
```toml
"networkx>=3.3",
"sqlite3",  # stdlib, no install needed — just document it
```

**Keep:**
```toml
"fastmcp>=3.0.2",
"gitpython>=3.1.46",
"pydantic>=2.12.5",
"rich>=14.3.3",
"tree-sitter>=0.25.2",
"typer>=0.24.1",
"python-dotenv>=1.0.0",
"pathspec>=1.0.4",
"pypdf>=5.1.0",
"tree-sitter-python>=0.25.0",
"tree-sitter-javascript>=0.25.0",
"tree-sitter-typescript>=0.23.2",
"tree-sitter-go>=0.25.0",
"tree-sitter-java>=0.23.5",
"tree-sitter-rust>=0.24.0",
"tree-sitter-ruby>=0.23.1",
"litellm>=1.82.0",  # keep if using LLM for summary generation
```

---

## Migration order (do not skip steps)

**Step 1 — New LoomGraph (Day 1–2)**
Write `src/loom/core/graph.py` with the SQLite + NetworkX implementation.
Keep all method signatures identical to what `ingest/pipeline.py` currently calls
(`bulk_create_nodes`, `bulk_create_edges`, `blast_radius`, `query`, `get_node`).
Add a shim `async def query(self, cypher, params)` that raises `NotImplementedError`
so remaining callers fail loudly, not silently.

**Step 2 — Update ingest pipeline (Day 2–3)**
Rewrite `ingest/pipeline.py` and `ingest/incremental.py` to call the new
`LoomGraph` methods directly. Remove all Cypher query strings. Replace
`_load_stored_file_hashes()` with `graph.get_content_hashes()`.
Remove calls to `SemanticLinker`, `embed_nodes`, `extract_summaries` (or
make summaries optional — they're nice to have, not required).

**Step 3 — Update query layer (Day 3)**
Rewrite `query/blast_radius.py` to call `graph.blast_radius()`.
Rewrite `query/traceability.py` to use direct SQL via `graph._conn()`.
Rewrite `query/node_lookup.py` to call `graph.get_nodes_by_name()`.

**Step 4 — Update CLI (Day 3–4)**
`cli/graph.py` — `blast_radius`, `calls`, `query`, `entrypoints` all rewrite
to call the new graph methods. Remove `loom relink`, `loom watch`.
Add `loom setup --hook` for post-commit hook installation.

**Step 5 — Delete dead code (Day 4)**
```
src/loom/core/falkor/      ← delete directory
src/loom/embed/            ← delete directory
src/loom/linker/           ← delete directory
src/loom/drift/            ← delete directory
src/loom/watch/            ← delete directory
src/loom/ingest/integrations/  ← delete directory
src/loom/ingest/connectors/    ← delete directory
src/loom/ingest/git_linker.py  ← delete file
src/loom/ingest/git_miner.py   ← delete file
src/loom/mcp/tools/tickets.py  ← delete file
docker-compose.yml             ← delete file
```

**Step 6 — Verify (Day 5)**
```bash
pip install -e ".[dev]"          # should install without model downloads
loom analyze .                   # analyze loom itself
loom blast_radius parse_python   # should return callers
loom serve                       # MCP server should start
```

Run `loom analyze` on 3 real repos and confirm:
- No Docker required
- No model download on first run
- `~/.loom/loom.db` created after analyze
- Blast radius returns correct callers

---

## What does NOT change

These files are the core of Loom and should not be touched during this migration:

```
src/loom/analysis/code/calls/    # CALLS edge extraction — keep entirely
src/loom/analysis/code/extractor.py  # Static summary extraction — keep
src/loom/analysis/code/parser.py     # keep
src/loom/analysis/code/noise_filter.py  # keep
src/loom/ingest/code/languages/  # All tree-sitter parsers — keep entirely
src/loom/ingest/code/registry.py # keep
src/loom/ingest/code/walker.py   # keep
src/loom/ingest/differ.py        # keep — still useful for incremental
src/loom/ingest/docs/            # keep — markdown/PDF parsing is useful
src/loom/core/node.py            # keep — Node model unchanged
src/loom/core/edge.py            # keep — Edge model, trim unused EdgeTypes
src/loom/mcp/server.py           # keep and simplify (see above)
src/loom/query/blast_radius.py   # keep logic, rewrite storage calls
src/loom/cli/                    # keep and simplify
```

---

## EdgeType — trim unused values

After removing Jira, GitHub, drift, and semantic linker, these EdgeTypes
are no longer produced by any pipeline. Remove them from `core/edge.py`
to keep the schema honest:

```python
# DELETE from EdgeType:
LOOM_IMPLEMENTS   # semantic linker removed
LOOM_VIOLATES     # drift detector removed
REALIZES          # ticket linker removed
CLOSES            # ticket linker removed
VERIFIED_BY       # ticket linker removed
DEPENDS_ON        # ticket connector removed

# KEEP:
CALLS             # core — call graph
CONTAINS          # core — file contains function
COUPLED_WITH      # keep — git coupling analysis
EXTENDS           # keep — inheritance
IMPORTS           # keep — import edges
MEMBER_OF         # keep — community membership
CHILD_OF          # keep — doc hierarchy
```

---

## What the Show HN demo looks like after this

```bash
pip install loom-tool        # no model download, no Docker required

git clone https://github.com/some/repo && cd repo
loom analyze .               # builds ~/.loom/loom.db in ~10 seconds

loom blast_radius validate_token
# → shows all callers transitively, ranked by depth

loom calls --target parse_python --direction both
# → callers and callees of parse_python

loom query "authentication"
# → functions matching the name

# MCP integration
loom serve
# → starts MCP server, works with Claude Code immediately
```

Zero infrastructure. Single SQLite file. Fast cold start.
This is what code-review-graph ships and why it got traction.

---

## Coding conventions (unchanged from existing codebase)

- Python 3.12, `ruff` for linting, `mypy --strict` for types
- `pydantic` v2 for all data models — no raw dict access
- Async throughout the CLI commands (`asyncio.run()` at the entry point)
- SQLite operations are sync (sqlite3 is not async) — wrap in `asyncio.to_thread`
  if called from async context
- Every public function has a docstring with Args/Returns
- `pytest` for tests, `pytest-asyncio` for async tests
- No silent fallbacks — raise clearly or log at WARNING minimum

---

*Last updated: April 2026*
*Context: Loom v0.1 shipped. This migration targets v0.2.*
