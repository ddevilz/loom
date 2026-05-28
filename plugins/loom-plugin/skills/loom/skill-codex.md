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

# Loom Workflow — Codex

> **Setup:** If Loom tools are not available, run `loom install` in the project
> root. This writes the MCP config to `~/.codex/mcp.json`.
> Restart Codex after running.
>
> **Multi-agent:** Codex supports `spawn_agent`. Use it for batch `store_understanding`
> calls when summarizing many functions — dispatch workers in parallel.

## Session start

```
start_session(agent_id="codex")      # store session_id for next time
```

If you have a previous session_id:
```
get_delta(previous_session_id="<id>")
```

Load `loom://primer` resource for a ~200-token codebase overview.

```
suggest_questions()                  # what to investigate this session
```

## Finding code

```
search_code("validate token")
```
If result has `summary` → read it, skip file. Summary is authoritative.
If no summary → call `get_context(node_id)` before opening the file.

## Reasoning about a function

```
get_context("function:src/auth.py:validate_token")
```
Returns: summary, signature, callers (top 10), callees (top 10), staleness flag.

## Impact analysis

```
get_blast_radius(node_id, depth=3)
get_context(node_id, callees_limit=0)   # callers only
get_context(node_id, callers_limit=0)   # callees only
```

## Storing understanding

Single:
```
store_understanding(node_id, summary)
```

Batch (up to 50) — prefer this when summarizing multiple functions:
```
store_understanding_batch([{"node_id": "...", "summary": "..."}, ...])
```

**Parallel batching with spawn_agent:** When you need to summarize > 20 functions,
dispatch multiple `store_understanding_batch` calls via `spawn_agent` in parallel.
Chunk the node list (20–25 per worker), spawn all workers in one message.

## Topology exploration

```
suggest_questions()           # dead code, bridge nodes, missing summaries
get_surprising_connections()  # cross-module hidden coupling
graph_stats(include_cohesion=True)   # per-cluster cohesion — low (<0.2) = refactor
get_work_plan()               # prioritized next actions: DOCUMENT / INVESTIGATE / EXPLORE / NOTHING
```

## Node ID format

`{kind}:{path}:{symbol}` — example: `function:src/auth.py:validate_token`
