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