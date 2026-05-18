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
| "What calls X?" | `get_callers(node_id)` |
| "What breaks if I change X?" | `get_blast_radius(node_id, depth=3)` |
| "What does X depend on?" | `get_callees(node_id)` |
| "How does A connect to B?" | `shortest_path(from_id, to_id)` |
| "What are the god nodes?" | `god_nodes(limit=10)` |
| "What changed since last session?" | `get_delta(previous_session_id=<id>)` |

## Store what you learn

After reading any file, write back:

```
store_understanding(node_id, "one sentence: what it does and why")
```

Good: `"Validates JWT against configured secret, returns False if expired or malformed."`
Bad: `"Handles auth."` / `"Calls jwt.decode()."`

Every summary written here is returned to future agents for free.

## Node ID format

`{kind}:{path}:{symbol}` — e.g. `function:src/auth.py:validate_token`

Use `search_code` to get node IDs; don't construct them manually.
