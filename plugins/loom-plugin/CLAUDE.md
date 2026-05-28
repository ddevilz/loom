# Loom Plugin — Code Search Protocol

Loom MCP is active. This repo's symbols are indexed in a local SQLite graph.

## Search: Loom before grep

Before using `grep`, `find`, or `Bash` to locate symbols:

1. `search_code("<keyword>")` — returns name, path, line, summary, signature instantly
2. `get_context(node_id)` — callers + callees + memo in one call; skip file reads if summary exists
3. Fall back to `grep` only when Loom returns no results or you need raw text matching

**Why:** Loom searches are 50–1500× cheaper in tokens than file reads. Summaries written by prior agents are returned for free.

## Orientation

At session start (or when exploring a new area):

```
start_session(agent_id="claude-code")   # enables visit tracking + delta awareness
graph_stats()                           # repo shape: node/edge counts by kind
get_work_plan()                         # prioritized DOCUMENT/INVESTIGATE/EXPLORE list
suggest_questions(limit=5)              # graph-topology-derived investigation priorities
```

## Common patterns

| Question | Loom call |
|---|---|
| "Where is X defined?" | `search_code("X")` |
| "Find all auth-related endpoints" | `search_code("tag:auth tag:api-endpoint")` |
| "What calls X?" | `get_context(node_id, callees_limit=0)` — callers in response |
| "What breaks if I change X?" | `get_blast_radius(node_id, depth=3)` |
| "What does X depend on?" | `get_context(node_id, callers_limit=0)` — callees in response |
| "How does A connect to B?" | `shortest_path(from_id, to_id)` |
| "What are the god nodes?" | `god_nodes(limit=10)` |
| "What changed since last session?" | `get_delta(previous_session_id=<id>)` |
| "What tests cover X?" | `get_context(node_id)` — check `tested_by` field |
| "How complex is X?" | `get_context(node_id)` — check `complexity` field |

## Store what you learn

After reading any file, write back:

```
store_understanding(node_id, "one sentence: what it does and why")
```

Good: `"Validates JWT against configured secret, returns False if expired or malformed."`
Bad: `"Handles auth."` / `"Calls jwt.decode()."`

Every summary written here is returned to future agents for free.

Optionally attach tags for future filtering:
```
store_understanding(node_id, summary, tags=["security-sensitive", "needs-refactor"])
```

Agent tags survive re-index — they are not overwritten by automatic tagging.

## Node ID format

`{kind}:{path}:{symbol}` — e.g. `function:src/auth.py:validate_token`

Use `search_code` to get node IDs; don't construct them manually.

## Tag search syntax

Use `tag:X` in any `search_code` or `loom query` call. Multiple tags are ANDed:

```
search_code("tag:auth")                   # nodes tagged "auth"
search_code("tag:api-endpoint tag:auth")  # tagged both
search_code("tag:async-task login")       # tagged "async-task" AND contains "login"
```

Auto-applied tags: `api-endpoint`, `async-task`, `auth`, `dead-code`, `entry-point`, `hub`, `bridge`, `test`, `migration`.
