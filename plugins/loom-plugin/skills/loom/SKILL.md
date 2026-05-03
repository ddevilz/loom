---
name: loom
description: >
  Use Loom MCP tools for code intelligence — symbol search, context packets,
  blast radius, session primer, delta context, topology insights. Invoke when
  working on any codebase indexed with `loom analyze .`.
trigger: >
  When connected to an MCP server named "loom" OR when user says "use loom"
  OR when search_code / get_context / store_understanding tools are available.
---

# Loom Workflow

Loom is a persistent symbol index. Every session gets faster as agent summaries
accumulate. Zero LLM cost — all data from tree-sitter + your own stored summaries.

## Session start

Call `loom://primer` resource (or `loom context` CLI) for a ~200-token codebase
overview. Skip file exploration — primer gives you modules, hot functions, coverage.

Then call `suggest_questions()` — surfaces dead code, bridge nodes, undocumented
hot functions, and low-cohesion clusters worth investigating:

```
suggest_questions()           # what to look at this session
get_surprising_connections()  # hidden coupling, unexpected cross-module bridges
```

If you have a `session_id` from last time:
```
get_delta(previous_session_id="<id>")  # only what changed
```
Otherwise:
```
start_session(agent_id="claude-code")  # store session_id for next time
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
get_callers("function:src/auth.py:validate_token")
get_callees("function:src/auth.py:validate_token")
```

## Storing understanding (do this every time)

After reading any function:
```
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature invalid."
)
```
Good summary: what it does + why it exists. One sentence.
Bad: "handles auth" (vague), "calls jwt.decode()" (describes HOW not WHY).

Batch version for efficiency:
```
store_understanding_batch([
    {"node_id": "...", "summary": "..."},
    ...
])
```

## Topology exploration

Use these to understand architecture and spot problems:

```
suggest_questions(limit=7)
```
Returns questions to investigate: dead code, god functions, missing summaries,
low-cohesion clusters. Best used at session start to prioritize work.

```
get_surprising_connections(limit=10)
```
CALLS edges that are non-obvious — cross-module, peripheral-to-hub, cross-community.
Each result includes human-readable reasons. Use when tracing unexpected dependencies.

```
get_community_cohesion()
```
Cohesion score per community (0.0–1.0). Low cohesion (<0.2) = refactor candidate.
Use when deciding where to split or consolidate modules.

## Node ID format

`{kind}:{path}:{symbol}`
Examples:
- `function:src/auth.py:validate_token`
- `class:src/models/user.py:User`
- `method:src/models/user.py:User.save`
- `file:src/auth.py`

## Key tools

| Tool | Use when |
|------|----------|
| `search_code(query)` | Finding symbols by name/keyword |
| `get_context(node_id)` | Full picture before reading source |
| `get_blast_radius(node_id)` | What breaks if this changes |
| `get_callers(node_id)` | Who calls this function |
| `get_callees(node_id)` | What this function calls |
| `get_neighbors(node_id)` | All connected nodes (any edge type) |
| `get_community(community_id)` | All members of a cluster |
| `shortest_path(from_id, to_id)` | Dependency path between two nodes |
| `store_understanding(node_id, summary)` | After understanding any function |
| `store_understanding_batch(updates)` | Batch summaries — up to 50 at once |
| `get_context(node_id)` | Full context packet — summary + callers + callees |
| `get_delta(previous_session_id)` | Session start — what changed |
| `start_session(agent_id)` | Register session, get session_id |
| `graph_stats()` | Repo overview: counts by kind |
| `god_nodes()` | Most-called functions (good entry points) |
| `suggest_questions()` | Session start — what to investigate |
| `get_surprising_connections()` | Hidden coupling, cross-module bridges |
| `get_community_cohesion()` | Cluster cohesion scores |
| `get_savings()` | Token savings report |
