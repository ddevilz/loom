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

# Loom Workflow — GitHub Copilot / VS Code

> **Setup:** If Loom tools are not available, add Loom MCP server manually in
> VS Code Settings → MCP Servers, or create `.vscode/mcp.json` in the workspace:
> ```json
> {"servers": {"loom": {"type": "stdio", "command": "uvx", "args": ["--from", "loom-tool", "loom-mcp"]}}}
> ```
> Reload the VS Code window after (`Developer: Reload Window`).

## Session start

```
start_session(agent_id="copilot")      # store session_id for next time
```

If you have a previous session_id:
```
get_delta(previous_session_id="<id>")
```

Load `loom://primer` resource for a ~200-token codebase overview.

```
suggest_questions()                    # what to investigate this session
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
get_callers(node_id)
get_callees(node_id)
```

## Storing understanding

```
store_understanding(node_id, summary)
```
Batch (up to 50):
```
store_understanding_batch([{"node_id": "...", "summary": "..."}, ...])
```

## Topology exploration

```
suggest_questions()           # dead code, bridge nodes, missing summaries
get_surprising_connections()  # cross-module hidden coupling
get_community_cohesion()      # cluster cohesion — low (<0.2) = refactor
get_work_plan()               # prioritized next actions: DOCUMENT / INVESTIGATE / EXPLORE / NOTHING
```

## Node ID format

`{kind}:{path}:{symbol}` — example: `function:src/auth.py:validate_token`
