---
name: loom-workflow
description: >
  Agent workflow for Loom MCP tools — persistent code intelligence layer.
  Search symbols, get context packets, store understanding, track deltas.
  Invoke when working in a repo indexed with `loom analyze .`.
version: "0.3"
author: Devashish <jadhavom24@gmail.com>
tags: [code-intelligence, mcp, search, context, memory]
---

# Loom Workflow Skill

**Announce:** "Using loom-workflow skill."

Loom is a persistent symbol index. Each session adds agent summaries.
Next session skips re-reading. Compounding token savings — 8× first use, 90×+ after.

---

## Session Start Protocol

### Step 1: Load primer (always)

Call the `loom://primer` MCP resource or run `loom context` CLI.
Returns ~200-token overview: modules, hot functions, summary coverage.
Replaces grep/file exploration for orientation.

### Step 2: Check delta (if prior session exists)

```
get_delta(previous_session_id="<stored-id>")
```

Returns only changed/deleted nodes since last session.
If `too_many_changes: true` → treat as fresh start, use search_code.

### Step 3: Register session

```
start_session(agent_id="claude-code")
```

Store the returned `session_id`. Pass to `get_delta` next session.

---

## Finding Code

```
search_code("validate token", limit=10)
```

Result includes `summary` and `signature` when cached.
**If summary present → skip file read.** Summary is agent-verified or auto-generated.

---

## Understanding a Function (one call)

```
get_context("function:src/auth.py:validate_token")
```

Returns:
- `summary` — what it does and why
- `signature` — full type-annotated signature
- `callers` — top 10 callers (sorted by frequency, same-file first)
- `callees` — top 10 callees
- `summary_stale` — true if source changed since summary written
- `callers_total` — actual count if truncated

If `summary_stale: true` → read source, update summary.

---

## Impact Analysis

```
get_blast_radius("function:src/auth.py:validate_token", depth=3)
get_callers("function:src/auth.py:validate_token")
get_callees("function:src/auth.py:validate_token")
```

---

## Storing Understanding (required after every read)

```
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature invalid."
)
```

**Good summary:** what + why, one sentence, no HOW.
- ✅ "Validates JWT tokens, returns False if expired or malformed."
- ❌ "Handles auth." (too vague)
- ❌ "Calls jwt.decode() then checks exp." (describes HOW, not WHY)

**Batch (when multiple functions understood):**
```
store_understanding_batch([
    {"node_id": "function:src/auth.py:validate_token", "summary": "..."},
    {"node_id": "function:src/auth.py:refresh_token", "summary": "..."},
])
```

---

## Node ID Format

`{kind}:{relative-path}:{symbol}`

| Kind | Example |
|------|---------|
| `function` | `function:src/auth.py:validate_token` |
| `method` | `method:src/models/user.py:User.save` |
| `class` | `class:src/models/user.py:User` |
| `file` | `file:src/auth.py` |

---

## Quick Reference

| Tool | When |
|------|------|
| `search_code(query)` | Find symbols by name/keyword |
| `get_context(node_id)` | Full picture before reading source |
| `get_blast_radius(node_id)` | Impact of changing a function |
| `get_callers(node_id)` | Who depends on this |
| `get_callees(node_id)` | What this depends on |
| `store_understanding(node_id, summary)` | After reading any function |
| `store_understanding_batch(updates)` | Multiple functions at once |
| `start_session(agent_id)` | Register session start |
| `get_delta(previous_session_id)` | What changed since last session |
| `graph_stats()` | Node/edge counts by kind |
| `god_nodes()` | Most-called functions (entry points) |
| `shortest_path(from_id, to_id)` | Call chain between two functions |

---

## Install

```bash
pip install loom-tool
loom analyze .     # index the repo
loom install       # configures Claude Code, Cursor, Windsurf, Codex + git hook
```

After `loom install`, this skill is written to `~/.claude/skills/loom.md`
and loaded automatically when the loom MCP server is connected.
