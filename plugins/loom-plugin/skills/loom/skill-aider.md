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

# Loom Workflow — Aider

> **Setup:** If Loom tools are not available, run `loom install` in the project
> root. Add `--mcp-server loom` to your aider invocation or `.aider.conf.yml`.
>
> **Multi-agent:** Aider runs sequentially — no parallel subagents. Use
> `store_understanding_batch` to batch summary writes in one call instead of many.

## Session start

```
suggest_questions()                  # what to investigate this session
start_session(agent_id="aider")      # store session_id for next time
```

If you have a previous session_id:
```
get_delta(previous_session_id="<id>")
```

## Finding code

```
search_code("validate token")
```
If result has `summary` → read it, skip file.
If no summary → call `get_context(node_id)`.

## Reasoning about a function

```
get_context("function:src/auth.py:validate_token")
```

## Impact analysis

```
get_blast_radius(node_id, depth=3)
get_callers(node_id)
get_callees(node_id)
```

## Storing understanding

Batch all summaries into one call — sequential platform, minimize round-trips:
```
store_understanding_batch([
    {"node_id": "...", "summary": "..."},
    {"node_id": "...", "summary": "..."},
])
```

## Topology exploration

```
suggest_questions()           # dead code, bridge nodes, missing summaries
get_surprising_connections()  # cross-module hidden coupling
get_community_cohesion()      # cluster cohesion — low (<0.2) = refactor
```

## Node ID format

`{kind}:{path}:{symbol}` — example: `function:src/auth.py:validate_token`
