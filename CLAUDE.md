# Loom — Agent Memory Layer

**What Loom is:** A persistent symbol index for AI coding agents.
Agents query it to find functions instantly. Agents populate summaries
as they work. The cache gets richer over time — zero LLM cost from Loom's side.

**Core loop:**
1. `loom analyze .` — tree-sitter extracts all symbols into `~/.loom/loom.db`
2. Agent calls `search_code("login")` → instant: `{name, path, line, summary}`
3. Agent reads only those lines, understands the function
4. Agent calls `store_understanding(id, "Validates JWT tokens for login")` → cached
5. Next agent/session: `search_code("login")` returns the summary already written
6. On `git commit` → post-commit hook fires → only changed files re-indexed

**Zero LLM calls from Loom. Claude Code populates summaries organically.**

---

## Current state (read before touching anything)

The migration from FalkorDB to SQLite is complete. Do not re-introduce:
- FalkorDB / Redis / Docker
- fastembed / sentence-transformers / infinity-emb / diskcache
- Jira / GitHub ticket connectors
- Semantic linker / embedding pipeline
- Cypher query strings anywhere

The database is `~/.loom/loom.db` (SQLite, WAL mode).
Two core tables: `nodes`, `edges`.
FTS5 virtual table `nodes_fts` provides full-text search on name + summary + path.
Schema lives in `src/loom/core/db.py`. Do not alter schema without updating `db.py`.

---

## Dead code — DELETE THESE FILES NOW

These files reference types/protocols that no longer exist in the codebase
(`NodeKind.TICKET`, `NodeSource.TICKET`, `EdgeOrigin`, `QueryGraph.query(cypher)`).
They will cause import errors if anything imports them. Delete cleanly:

```
src/loom/ingest/connectors/
  __init__.py
  base.py                          # TicketConnector, TicketFetchResult
  github_issues.py                 # references NodeKind.TICKET, NodeSource.TICKET

src/loom/ingest/git_linker.py      # references EdgeOrigin, QueryGraph.query(cypher)
src/loom/ingest/git_miner.py       # references subprocess git, no graph usage left

src/loom/mcp/tools/tickets.py      # references traceability module (already gone)
src/loom/mcp/tools/__init__.py     # empty after above is deleted — remove too

src/loom/core/types.py             # dead — has QueryGraph protocol with .query(cypher)

src/loom/analysis/code/communities.py  # OLD FalkorDB Cypher version
                                       # duplicate of src/loom/analysis/communities.py
src/loom/analysis/code/coupling.py     # OLD FalkorDB Cypher version
                                       # duplicate of src/loom/analysis/coupling.py
```

After deleting, clean up residual imports:

In `src/loom/core/edge.py`:
- Remove `DEPENDS_ON` from EdgeType (only used by deleted github_issues.py)
- Remove `LOOM_IMPLEMENTS`, `LOOM_VIOLATES`, `REALIZES`, `CLOSES`, `VERIFIED_BY`
  if they appear — none are produced by any remaining pipeline

In `src/loom/core/__init__.py`:
- Verify `ConfidenceTier` is still used somewhere before removing its export

Verify after deletion:
```bash
python -c "import loom"
python -c "from loom.mcp.server import build_server"
python -c "from loom.ingest.pipeline import index_repo"
```
All three should import without error.

---

## Bug fix — `src/loom/__init__.py`

The `return` statement sits before the `try/except` for winloop,
so Windows users never get winloop installed. Fix:

```python
def _install_fast_event_loop() -> None:
    if sys.platform == "win32":
        # Remove the bare `return` that was here
        try:
            import winloop  # type: ignore
            winloop.install()
        except ImportError:
            pass
        return  # ← return belongs here, after the try/except

    try:
        import uvloop  # type: ignore
        uvloop.install()
    except ImportError:
        pass
```

---

## New feature — `store_understanding` MCP tool

This is the core feature that makes Loom an agent memory layer.
When Claude Code reads and understands a function, it calls this tool.
Loom writes the summary to SQLite. Next session, any agent searching
gets the summary without re-reading the source file.

### Step 1: Add `update_summary()` to `src/loom/core/graph.py`

Add this method to the `LoomGraph` class:

```python
async def update_summary(self, node_id: str, summary: str) -> bool:
    """Store an agent-generated summary for a node.

    Args:
        node_id: Exact node id (e.g. 'function:src/auth.py:validate_token').
        summary: One-sentence description of what the function does and why.

    Returns:
        True if the node exists and was updated, False if node_id not found.
    """
    def _run() -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE nodes SET summary = ?, updated_at = ? WHERE id = ?",
                (summary.strip(), int(time.time()), node_id),
            )
            conn.commit()
            return cur.rowcount > 0
    return await asyncio.to_thread(_run)
```

### Step 2: Add tools to `src/loom/mcp/server.py`

Add both tools inside `build_server()`, alongside the existing tools:

```python
@mcp.tool()
async def store_understanding(node_id: str, summary: str) -> dict:
    """Cache what you learned about a function so future agents skip re-reading it.

    Call this after you have read and understood any function or class.
    The summary is stored permanently in loom.db and returned on future searches.

    Args:
        node_id: The exact node id from search_code results.
                 Example: 'function:src/auth.py:validate_token'
        summary: One sentence — what does this do and WHY does it exist?
                 Good: 'Validates JWT tokens and returns False if expired or malformed.'
                 Bad:  'Handles authentication.' (too vague)
                 Bad:  'Calls jwt.decode() then checks exp field.' (describes HOW not WHY)
    """
    nid = _req_text(node_id, field="node_id", max_length=_MAX_ID)
    s = _req_text(summary, field="summary", max_length=500)
    ok = await graph.update_summary(nid, s)
    return {"stored": ok, "node_id": nid}


@mcp.tool()
async def store_understanding_batch(updates: list[dict]) -> dict:
    """Cache summaries for multiple functions in one call. Max 50 per call.

    Args:
        updates: List of {node_id: str, summary: str} dicts.
    """
    if len(updates) > 50:
        updates = updates[:50]
    stored = 0
    for item in updates:
        nid = str(item.get("node_id", "")).strip()
        s = str(item.get("summary", "")).strip()
        if nid and s:
            ok = await graph.update_summary(nid, s)
            if ok:
                stored += 1
    return {"stored": stored, "total": len(updates)}
```

---

## New CLI command — `loom summaries`

Add to `src/loom/cli/graph.py` to let developers see what agents have learned:

```python
@app.command()
def summaries(
    db: Path | None = typer.Option(None, "--db"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Show functions with agent-written summaries (most recent first)."""
    import asyncio

    g = LoomGraph(db_path=db)

    def _run():
        with g._lock:
            conn = g._connect()
            return conn.execute(
                "SELECT id, name, path, summary FROM nodes "
                "WHERE summary IS NOT NULL AND kind NOT IN ('file', 'community') "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    rows = asyncio.run(asyncio.to_thread(_run))
    t = Table("name", "path", "summary")
    for r in rows:
        t.add_row(r["name"], r["path"], (r["summary"] or "")[:70])
    console.print(t)
```

Export it from `src/loom/cli/__init__.py`:
```python
from loom.cli.graph import (
    blast_radius, callers, callees, query, stats, summaries  # add summaries
)
```

---

## Agent instructions — add to CLAUDE.md at repo root

This tells Claude Code how to use Loom tools in practice:

```markdown
## Using Loom (required workflow)

Loom is a persistent symbol index for this codebase. It is faster than
reading files and preserves understanding across sessions.

**Before searching for any function:**
1. Call `search_code("keyword")` first
2. If the result has a `summary`, read that instead of the file
3. Only read the actual source if you need the implementation details

**After understanding a function:**
Always call `store_understanding(node_id, summary)` with one sentence
describing what the function does and WHY it exists.
- Good: `"Validates JWT tokens, returns False if expired or signature invalid."`
- Bad: `"Handles auth."` (too vague)
- Bad: `"Calls jwt.decode()."` (describes HOW, not WHY)

**For impact analysis:**
- `get_blast_radius(node_id)` — what else breaks if this changes
- `get_callers(node_id)` — who calls this function
- `get_callees(node_id)` — what does this function call

**Node ID format:** `kind:path:symbol`
Example: `function:src/auth.py:validate_token`
```

---

## What does NOT need to change

Do not touch these files. They are working correctly:

```
src/loom/core/db.py              # SQLite schema + FTS5 — correct
src/loom/core/graph.py           # LoomGraph — add update_summary() only
src/loom/core/node.py            # Node model — correct
src/loom/core/edge.py            # EdgeType — trim dead EdgeTypes after connectors deleted
src/loom/core/content_hash.py    # SHA-256 helpers — correct

src/loom/ingest/pipeline.py      # index_repo, _parse_file, resolve_calls — correct
src/loom/ingest/incremental.py   # sync_paths — correct
src/loom/ingest/utils.py         # sha256_of_file — correct
src/loom/ingest/code/            # ALL tree-sitter parsers — do not touch
src/loom/ingest/docs/            # Markdown/PDF parsing — keep

src/loom/analysis/communities.py # Louvain + NetworkX — correct
src/loom/analysis/coupling.py    # git co-change analysis — correct
src/loom/analysis/dead_code.py   # dead code marking — correct
src/loom/analysis/code/calls/    # CALLS edge extraction — do not touch
src/loom/analysis/code/extractor.py  # static summary extraction — keep
src/loom/analysis/code/parser.py     # parse_repo — keep
src/loom/analysis/code/noise_filter.py # noise filtering — keep

src/loom/cli/install.py          # loom install — handles 4 platforms + git hook
src/loom/cli/export.py           # loom export HTML — keep
src/loom/cli/graph.py            # add summaries command only
src/loom/cli/ingest.py           # loom analyze, sync, serve — correct
src/loom/cli/analysis.py         # loom communities, dead-code — correct

src/loom/mcp/server.py           # add store_understanding tools only
src/loom/query/blast_radius.py   # blast radius payload — correct
src/loom/query/node_lookup.py    # resolve node by name — correct
src/loom/query/search.py         # SearchResult wrapper — correct

src/loom/config.py               # env vars — correct
src/loom/devtools.py             # dep checker, test runner — keep
```

---

## Steps — do in order, do not skip

**Step 1 — Delete dead files (30 min)**
Delete every file listed in "Dead code" above.
Then run: `python -c "import loom"` — must not error.

**Step 2 — Fix winloop bug (5 min)**
Apply the fix in `src/loom/__init__.py`.

**Step 3 — Add `update_summary()` to LoomGraph (15 min)**
Add method to `src/loom/core/graph.py` exactly as specified above.

**Step 4 — Add MCP tools (20 min)**
Add `store_understanding` and `store_understanding_batch` to `src/loom/mcp/server.py`.

**Step 5 — Add `loom summaries` CLI command (15 min)**
Add to `src/loom/cli/graph.py`, export from `src/loom/cli/__init__.py`.

**Step 6 — Update repo CLAUDE.md (10 min)**
Add the agent workflow instructions to the repo's own `CLAUDE.md`.

**Step 7 — Smoke test**
```bash
pip install -e ".[dev]"
loom analyze .
loom query "parse_python"
loom summaries        # should show empty table (no summaries yet)
loom serve            # MCP server starts, no errors
```

---

## Show HN demo after this is done

```bash
pip install loom-tool           # no model download, no Docker

cd my-repo
loom analyze .                  # ~10 seconds for 500-file repo
loom install                    # configures Claude Code, Cursor, Codex, Windsurf
                                # installs post-commit hook automatically

# Claude Code session:
# > search_code("validate token")  → instant, with cached summaries
# > get_blast_radius("function:src/auth.py:validate_token")  → callers
# > store_understanding(id, "Validates JWT, returns False if expired")  → cached

loom summaries                  # see everything agents have learned
loom export                     # interactive HTML graph, opens in browser
```

---

## Coding conventions

- Python 3.12, ruff for linting, mypy --strict for type checking
- All SQLite operations are synchronous — always wrap in `asyncio.to_thread()`
- `threading.RLock` (graph._lock) must wrap every SQLite call
- No silent fallbacks — raise or log at WARNING minimum
- Every public method has a docstring with Args/Returns
- pytest + pytest-asyncio for all tests
- Node IDs follow the pattern: `{kind}:{path}:{symbol}`
  Example: `function:src/auth.py:validate_token`

---

*Loom v0.2 — April 2026*

---

## v0.3 Superpowers — Context Layer (Design)

**Goal:** Eliminate file reads. Agent reasons from Loom data alone.
**Metric:** 8× token savings on first use → 90× on session 2+.
**Principle:** Zero new LLM cost. All data from tree-sitter + agent summaries.

### Priority Order

1. **Enrich `search_code`** — lowest effort, highest immediate impact
2. **`get_context` MCP tool** — context packets, single-call reasoning
3. **Auto-summaries on analyze** — baseline coverage from day zero
4. **`loom context` CLI / MCP resource** — session primer
5. **Delta context** — session tracking, v0.4

---

### Feature 1: Enrich `search_code` (P0 — do first)

**Problem:** `search_code` returns `{id, name, path, kind, score}`. Strips summary.
Agent must call `get_node` separately to see summary. Wastes a round-trip.

**Fix:** Include `summary` and `signature` from metadata in search results:

```python
# In server.py search_code tool
return [
    {
        "id": r.node.id,
        "name": r.node.name,
        "path": r.node.path,
        "kind": r.node.kind.value,
        "score": r.score,
        "summary": r.node.summary,                           # ADD
        "signature": r.node.metadata.get("signature"),       # ADD
        "line": r.node.start_line,                           # ADD
    }
    for r in results
]
```

**Why `signature` is free:** Python/TS/Java parsers already store
`metadata.signature` during `loom analyze`. No schema change needed.

**Impact:** Agent gets summary + signature in search results.
If summary exists, agent skips file read entirely. 8× multiplier.

---

### Feature 2: `get_context` MCP tool (P0 — context packets)

**Problem:** To reason about a function, agent needs:
1. What it does (summary)
2. What it looks like (signature)
3. Who calls it (callers)
4. What it calls (callees)

Currently 4 separate MCP tool calls. Should be 1.

**Design:** Single SQL query with edge JOINs:

```python
@mcp.tool()
async def get_context(node_id: str) -> dict | None:
    """Everything an agent needs to reason about a function — one call.

    Returns summary, signature, callers, callees, and community.
    If the summary exists, you do NOT need to read the source file.
    """
    # 1. Get node
    # 2. Get callers (edges WHERE to_id = node_id AND kind = 'calls')
    # 3. Get callees (edges WHERE from_id = node_id AND kind = 'calls')
    # All in one _run() with db._lock
```

**Return shape (~80 tokens):**

```json
{
    "id": "function:src/auth.py:validate_token",
    "name": "validate_token",
    "path": "src/auth.py",
    "line": 42,
    "signature": "validate_token(token: str, secret: str) -> bool",
    "summary": "Validates JWT tokens, returns False if expired or malformed.",
    "callers": [{"name": "login_handler", "path": "src/routes.py"}],
    "callees": [{"name": "decode_jwt", "path": "src/crypto.py"}],
    "community_id": "auth-cluster",
    "is_stale": false
}
```

**Staleness detection:** Compare `content_hash` at summary-write time vs current.
Add `summary_hash TEXT` column to `nodes` — stores content_hash when summary was
written. If `content_hash != summary_hash`, mark `is_stale: true`. Agent knows
to re-read source and update summary.

**Schema change needed:**

```sql
ALTER TABLE nodes ADD COLUMN summary_hash TEXT;
-- Set when store_understanding writes a summary
-- Compared against content_hash to detect staleness
```

**Cap callers/callees at 10 each** in response. Mention `"callers_total": 47`
if truncated so agent knows more exist.

---

### Feature 3: Auto-summaries on `loom analyze` (P1)

**Problem:** Without agent-written summaries, search results have no summary.
Agent must read file. The cold-start problem.

**Solution:** `extract_summary()` already exists in `analysis/code/extractor.py`.
It builds structured text from metadata (params, return type, docstring) — zero LLM.
But it's never called during the analyze pipeline.

**Fix:** Call `extract_summaries()` in `index_repo()` before storing nodes.
Only for nodes that don't already have an agent-written summary.

```python
# In ingest/pipeline.py index_repo()
from loom.analysis.code.extractor import extract_summaries

# After parsing, before storing:
nodes = await extract_summaries(nodes)  # fills summary from metadata
# This preserves agent summaries (they're already set)
```

**Wait — check `extract_summaries` logic:**
```python
def extract_summaries(nodes):
    return [
        n if n.summary else n.model_copy(update={"summary": extract_summary(n)})
        for n in nodes
    ]
```

Only fills if `n.summary` is None. Agent summaries preserved. Safe.

**BUT** — there's a problem. `bulk_upsert_nodes` does `ON CONFLICT DO UPDATE SET
summary=excluded.summary`. If re-analyzing overwrites agent summaries with
auto-generated ones, that's data loss.

**Fix:** Change upsert to preserve existing non-null summaries:

```sql
ON CONFLICT(id) DO UPDATE SET
    summary = CASE
        WHEN excluded.summary IS NOT NULL AND nodes.summary IS NULL
        THEN excluded.summary
        WHEN excluded.summary IS NOT NULL AND nodes.summary_hash IS NOT NULL
             AND nodes.content_hash != excluded.content_hash
        THEN excluded.summary  -- source changed, auto-summary is fresher
        ELSE nodes.summary     -- keep agent summary
    END,
```

Actually simpler approach: **don't pass auto-summaries through upsert at all.**
Run `extract_summaries` as a post-pass UPDATE only on nodes with NULL summary.
Keeps upsert logic clean.

```python
# After bulk_upsert_nodes:
await _fill_auto_summaries(db)  # UPDATE nodes SET summary = ... WHERE summary IS NULL
```

**Impact:** Every function has a baseline summary from day zero.
Agent-written summaries override. Auto-summaries are better than nothing.
Coverage goes from 0% → ~80% immediately after first `loom analyze`.

---

### Feature 4: Session Primer — `loom context` (P1)

**Problem:** Every Claude Code session starts with 3,000-10,000 tokens exploring
the codebase. Re-reading CLAUDE.md, grepping to orient, re-discovering structure.

**Solution:** 200-token compressed primer. Two delivery mechanisms:

**CLI: `loom context`**

```bash
$ loom context
Repo: loom (Python, 47 files, 312 functions, 8 modules)
Modules: core(78fn) ingest(45fn) mcp(12fn) query(23fn) cli(15fn) analysis(18fn)
Entry points: build_server(), index_repo(), main()
Hot functions: search(42 callers), _row_to_node(38), connect(29)
Summary coverage: 267/312 (86%) — 23 agent-written, 244 auto-generated
Last analyzed: 2026-04-24 08:30
```

**MCP resource: `loom://primer`**

```python
@mcp.resource("loom://primer")
async def primer() -> str:
    """Compressed codebase overview. Load at session start."""
```

Claude Code / Cursor can auto-load MCP resources. Zero-effort onboarding.

**Data sources — all existing:**
- `graph_stats()` → node/edge counts by kind
- `god_nodes(5)` → most-called functions (entry points proxy)
- `SELECT COUNT(*) FROM nodes WHERE summary IS NOT NULL` → coverage
- `SELECT DISTINCT path FROM nodes` → module clustering (group by first path segment)

**No new tables. No schema changes. Pure view over existing data.**

---

### Feature 5: Delta Context (P2 — v0.4)

**Problem:** Re-reading unchanged functions wastes tokens.
If agent worked on auth.py yesterday and nothing changed, skip it.

**Revised design (simpler than original brainstorm):**

**Don't track individual node reads. Track session timestamps.**

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT 'default',
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER,
    node_count  INTEGER DEFAULT 0,     -- how many nodes existed
    summary_count INTEGER DEFAULT 0    -- how many had summaries
);
```

**How it works:**

1. `start_session(agent_id)` → records timestamp, returns session_id
2. Agent works normally (search, get_context, store_understanding)
3. Next session: `get_delta(agent_id)` →

```python
@mcp.tool()
async def get_delta(agent_id: str = "default") -> dict:
    """What changed since your last session. Start here."""
    # Find last session for this agent
    # SELECT * FROM nodes WHERE updated_at > last_session.started_at
    # Return context packets for changed nodes only
```

**Why this is simpler:**
- No `session_reads` table (was write-heavy per query)
- Uses existing `nodes.updated_at` — already maintained
- `content_hash` changes detect source modifications
- `updated_at` changes detect summary updates
- One query: `WHERE updated_at > ?`

**Return shape:**

```json
{
    "since": "2026-04-23T14:30:00",
    "changed": [/* context packets for modified nodes */],
    "new": [/* context packets for new nodes */],
    "deleted_ids": ["function:src/old.py:removed_fn"],
    "unchanged": 287,
    "summary": "3 functions changed in src/auth.py, 1 new file src/billing.py"
}
```

**Cleanup:** Keep last 20 sessions per agent. Prune on `loom analyze`.

**Impact:** Session 2+ agent gets ~400 tokens instead of ~8,000.
Only reads what actually changed. 90× multiplier when 80%+ is cached.

---

### Schema Changes Summary (v0.3)

```sql
-- Only one new column
ALTER TABLE nodes ADD COLUMN summary_hash TEXT;

-- Only one new table (can defer to v0.4)
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT 'default',
    started_at  INTEGER NOT NULL,
    ended_at    INTEGER,
    node_count  INTEGER DEFAULT 0,
    summary_count INTEGER DEFAULT 0
);
```

Update `src/loom/core/db.py` DDL to include both.

---

### New MCP Tools Summary (v0.3)

| Tool | Purpose | Priority |
|------|---------|----------|
| `get_context(node_id)` | Context packet — summary + sig + callers + callees | P0 |
| `start_session(agent_id)` | Begin session tracking | P2 (v0.4) |
| `get_delta(agent_id)` | Changed nodes since last session | P2 (v0.4) |

**Existing tools to modify:**
- `search_code` — add `summary`, `signature`, `line` to response
- `store_understanding` — set `summary_hash = content_hash` when writing

---

### New CLI Commands Summary

| Command | Purpose | Priority |
|---------|---------|----------|
| `loom context` | Session primer (200-token codebase overview) | P1 |

---

### Implementation Order

```
v0.3.0 — Context Packets (ship for Show HN)
  1. Enrich search_code with summary + signature + line
  2. Add get_context MCP tool
  3. Wire extract_summaries into analyze pipeline
  4. Add loom context CLI command
  5. Add summary_hash column + staleness detection
  6. Add loom://primer MCP resource

v0.4.0 — Delta Context
  7. Add sessions table
  8. Add start_session / get_delta MCP tools
  9. Prune old sessions on loom analyze
```

---

### Defensibility

1. **store_understanding flywheel** — every session makes Loom smarter.
   No other tool has write-back. Sourcegraph/ctags/LSP are read-only.
2. **Auto-summaries as floor** — 80% coverage from day zero.
   Agent summaries raise quality. Both layers compound.
3. **Delta context is lock-in** — switching tools means re-reading everything.
   Loom remembers what you know.
4. **Zero LLM cost** — competitors (Aider repo map, Cursor indexing) burn tokens.
   Loom piggybacks on work agent already does.

---

### Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Stale summaries mislead agent | `summary_hash` vs `content_hash` → `is_stale` flag |
| Auto-summaries low quality | They're structured metadata dumps, not prose. Better than nothing. Agent overwrites with better ones |
| Callers/callees query slow for hot functions | Cap at 10, return total count. Single SQL with LIMIT |
| Agent ignores store_understanding | CLAUDE.md instructions + eventually auto-prompt in MCP tool descriptions |
| Upsert overwrites agent summaries | Post-pass UPDATE for auto-summaries, not in upsert path |