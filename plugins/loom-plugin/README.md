# Loom — Agent Memory Layer Plugin

Persistent symbol index for AI coding agents. Tree-sitter indexes your repo into SQLite once. Agents search by keyword and get summaries + signatures instantly. Zero LLM cost — agent-written summaries accumulate across sessions.

## Install

**Prerequisite:** [uv](https://astral.sh/uv) must be installed first.

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
winget install astral-sh.uv
```

The MCP server installs on demand via `uvx` (no pip install required):

```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["--from", "loom-tool", "loom-mcp"]
    }
  }
}
```

Run `loom install` to auto-write this config to Claude Code, Cursor, Windsurf, or Codex.

## Quick Start

```bash
cd loom
loom analyze .        # tree-sitter indexes all symbols → ~/.loom/loom.db
loom install          # writes MCP config + installs post-commit hook
```

After that, the MCP server starts automatically when Claude Code opens the repo.

## Database Path

Resolved in this order:
1. `LOOM_DB_PATH` env var (if set) — absolute override
2. `~/.loom/projects/{git-root-name}.db` — per-project DB when inside a git repo
3. `~/.loom/loom.db` — global fallback (non-git directories)

Both `loom analyze` and `loom-mcp` use the same resolution logic via `resolve_db_path()`.

## Auto-Index

If the resolved DB is empty, `loom-mcp` auto-indexes the current directory in the background before serving. You don't need to run `loom analyze` manually on first use.

## MCP Tools (17)

| Tool | Purpose |
|------|---------|
| `search_code(query)` | FTS5 — returns summary + signature if cached |
| `get_context(node_id, brief?, callers_limit?, callees_limit?)` | Full context: summary, callers, callees. `brief=True` = metadata only. `callers_limit=0` / `callees_limit=0` = skip traversal. |
| `get_blast_radius(node_id, depth)` | Transitive callers — what breaks if this changes |
| `get_neighbors(node_id, depth, limit)` | All connected nodes across all edge types |
| `get_community(community_id, limit)` | All members of a Louvain community cluster |
| `shortest_path(from_id, to_id)` | Shortest path on CALLS subgraph |
| `graph_stats(include_cohesion?)` | Node/edge counts. `include_cohesion=True` adds per-cluster scores. |
| `god_nodes(limit)` | Most-called functions (unofficial entry points) |
| `store_understanding(node_id, summary)` | Write agent-generated summary to SQLite |
| `store_understanding_batch(updates)` | Batch summary writes (max 50) |
| `get_savings()` | Token savings from cache hits |
| `get_status()` | Node count + DB health check |
| `start_session(agent_id)` | Register session, returns unannotated_reads + annotation_gaps |
| `get_delta(previous_session_id)` | Changed nodes since last session |
| `get_surprising_connections(limit)` | Non-obvious cross-module CALLS edges |
| `suggest_questions(limit)` | Graph-topology investigation priorities |
| `get_work_plan()` | Prioritized next actions: DOCUMENT / INVESTIGATE / EXPLORE / NOTHING |

## MCP Resources

| Resource | Purpose |
|----------|---------|
| `loom://primer` | 200-token codebase overview — load at session start |
| `loom://savings` | Token savings report across all sessions |

## Agents

| Agent | Role |
|-------|------|
| `navigator` | Code exploration — find functions, trace call chains, understand architecture |
| `summarizer` | Documentation — read functions, write summaries back to Loom |
| `analyst` | Impact analysis — blast radius, hidden dependencies, change risk |

## Skills

| Skill | Use |
|-------|-----|
| `onboard` | First-time repo setup (analyze + install + orient) |
| `explore-code` | Navigate codebase with Loom search and context packets |
| `impact-analysis` | Assess change risk before modifying code |
| `document-code` | Read undocumented functions and store summaries |

## Commands (Slash)

| Command | Does |
|---------|------|
| `/loom-analyze` | Run `loom analyze .` to index the repo |
| `/loom-context` | Load `loom://primer` for session orientation |
| `/loom-summaries` | Show what agents have learned (most recent first) |
| `/loom-blast` | Blast radius of a function |
| `/loom-delta` | What changed since last session |
| `/loom-topology` | Architecture insights: god nodes, cohesion, surprising connections |
| `/loom-savings` | Token savings report |

## Core Workflow

```
# Session start
start_session(agent_id="claude-code")   # → session_id, unannotated_reads, annotation_gaps
get_delta(previous_session_id=<id>)      # only what changed

# Finding code
search_code("validate token")            # FTS5 — gets summary if cached
get_context("function:src/auth.py:validate_token")  # full context packet

# After reading any function
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature is invalid."
)

# Impact analysis before a change
get_blast_radius("function:src/auth.py:validate_token", depth=3)
get_surprising_connections(limit=10)
```

## Node ID Format

`{kind}:{path}:{symbol}`

- `function:src/auth.py:validate_token`
- `class:src/models/user.py:User`
- `method:src/models/user.py:User.save`
- `file:src/auth.py`

## Token Savings

Loom tracks how many tokens it saves:
- **Agent hits** — summaries written by `store_understanding` — file reads provably skipped
- **Auto hits** — structural summaries from `loom analyze` — baseline coverage
- Session 1: ~8× multiplier (summaries found instead of file reads)
- Session 2+: ~90× multiplier (delta context skips unchanged functions)

## Verification

```bash
bash plugins/loom-plugin/scripts/smoke.sh
# Expected: 10 passed, 0 failed
```

## CLI Reference

```bash
loom analyze .              # Index repo with tree-sitter
loom install                # Configure MCP + install post-commit hook
loom query "validate token" # Search from terminal
loom summaries              # See agent-written summaries
loom context                # Session primer (200 tokens)
loom blast-radius <name>    # Blast radius from terminal
loom export                 # Interactive HTML graph
```
