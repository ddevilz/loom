---
name: loom
description: >
  Use Loom MCP tools for code intelligence — symbol search, context packets,
  blast radius, session primer, delta context, topology insights. Invoke when
  working on any codebase indexed with `loom analyze .`.
trigger: >
  When connected to an MCP server named "loom" OR when user says "use loom"
  OR when search_code / get_context / store_understanding tools are available.
allowed-tools:
  - mcp__loom__search_code
  - mcp__loom__get_node
  - mcp__loom__get_context
  - mcp__loom__get_callers
  - mcp__loom__get_callees
  - mcp__loom__get_blast_radius
  - mcp__loom__get_neighbors
  - mcp__loom__get_community
  - mcp__loom__get_community_cohesion
  - mcp__loom__shortest_path
  - mcp__loom__graph_stats
  - mcp__loom__god_nodes
  - mcp__loom__store_understanding
  - mcp__loom__store_understanding_batch
  - mcp__loom__get_savings
  - mcp__loom__start_session
  - mcp__loom__get_delta
  - mcp__loom__get_surprising_connections
  - mcp__loom__suggest_questions
  - Read
  - Glob
---

# Loom Workflow

Loom is a persistent symbol index. Every session gets faster as agent summaries
accumulate. Zero LLM cost — all data from tree-sitter + your own stored summaries.

## Session start

**Step 1 — register session first:**
```
start_session(agent_id="claude-code")   # → session_id, save for next time
```
If you have a `session_id` from last time, use delta instead:
```
get_delta(previous_session_id="<id>")   # only what changed — skip unchanged nodes
```

**Step 2 — load primer:**

Call `loom://primer` resource (or `loom context` CLI) for a ~200-token codebase
overview. Skip file exploration — primer gives you modules, hot functions, coverage.

**Step 3 — prioritize work:**
```
suggest_questions()           # dead code, bridge nodes, missing summaries, low cohesion
get_surprising_connections()  # hidden coupling, unexpected cross-module bridges
```

## Finding code

```
search_code("validate token")   # FTS5 — returns summary + signature if cached
```
If result has `summary` → read it, skip file. Summary is authoritative.
If no summary → use `get_context(node_id)` before opening the file.

## Reasoning about a function

```
get_context("function:src/auth.py:validate_token")
```
Returns: summary, signature, callers (top 10), callees (top 10), staleness flag.
If `summary_stale: true` → source changed since summary written → re-read + update.

## Impact analysis

```
get_blast_radius("function:src/auth.py:validate_token", depth=3)
```
Each result includes `summary` — read it directly. Only call `get_context` on nodes
where `summary` is null or you need callers/callees of that node too.

```
get_callers("function:src/auth.py:validate_token")   # each result has summary
get_callees("function:src/auth.py:validate_token")   # each result has summary
```

## Topology exploration

```
get_surprising_connections(limit=10)
```
Returns `caller_summary` and `callee_summary` on each result — read these before
deciding whether to investigate further. No extra `get_context` calls needed.

```
get_community_cohesion()
```
Cohesion score per community (0.0–1.0). Low cohesion (<0.2) = refactor candidate.

```
suggest_questions(limit=7)
```
Question types: `dead_code`, `bridge_node`, `missing_summary`, `low_cohesion`.

## Storing understanding (do this every time)

After reading any function:
```
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature invalid."
)
```
Good summary: what it does + why it exists. One sentence. Under 120 chars.
Bad: "handles auth" (vague), "calls jwt.decode()" (describes HOW not WHY).

Batch version for efficiency:
```
store_understanding_batch([
    {"node_id": "...", "summary": "..."},
    ...
])
```
Max 50 per call. `store_understanding` is idempotent — skips write if content_hash
unchanged. Pass `force=True` to overwrite a stale summary.

## Node ID format

`{kind}:{path}:{symbol}`
Examples:
- `function:src/auth.py:validate_token`
- `class:src/models/user.py:User`
- `method:src/models/user.py:User.save`
- `file:src/auth.py`

## DB path

Resolved in order: `LOOM_DB_PATH` env → `~/.loom/projects/{git-root-name}.db` → `~/.loom/loom.db`

## Key tools

| Tool | Use when |
|------|----------|
| `search_code(query)` | Finding symbols by name/keyword |
| `get_node(node_id)` | Single node lookup by exact ID |
| `get_context(node_id)` | Full picture: summary + callers + callees + staleness |
| `get_blast_radius(node_id)` | Transitive callers — each result includes summary |
| `get_callers(node_id)` | Direct callers — each result includes summary |
| `get_callees(node_id)` | Direct callees — each result includes summary |
| `get_neighbors(node_id)` | All connected nodes (any edge type) — includes summary |
| `get_community(community_id)` | All members of a cluster — includes summary |
| `shortest_path(from_id, to_id)` | Dependency path — each hop includes summary |
| `store_understanding(node_id, summary)` | After understanding any function |
| `store_understanding_batch(updates)` | Batch summaries — up to 50 at once |
| `start_session(agent_id)` | Session start — get session_id |
| `get_delta(previous_session_id)` | Session start — only what changed |
| `graph_stats()` | Repo overview: counts by kind |
| `god_nodes()` | Most-called functions (entry points) |
| `suggest_questions()` | Investigation priorities from graph topology |
| `get_surprising_connections()` | Hidden coupling — returns caller/callee summaries |
| `get_community_cohesion()` | Cluster cohesion scores |
| `get_savings()` | Token savings from cache hits |
