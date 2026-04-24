# Loom Usage Guide

Day-to-day usage: install, index, query, serve, maintain.

## Prerequisites

- Python 3.12+
- `uv` (recommended) or `pip`
- No Docker, no external services

## Install

```bash
pip install loom-tool
# or:
uv add loom-tool
```

## Index a repository

```bash
cd my-repo
loom analyze .
```

What `loom analyze` does:
- walks repo (gitignore-aware)
- parses changed/new files with tree-sitter
- stores nodes + edges in `~/.loom/loom.db`
- computes communities (Louvain) and coupling (git co-change)
- marks dead code (no incoming CALLS)
- fills auto-summaries for nodes with no summary
- soft-deletes nodes for files removed from disk
- prunes old sessions (keeps last 20 per agent)

Only changed files are re-parsed (SHA-256 comparison). Fast on subsequent runs.

Use `--db` to override the database path:

```bash
loom --db ./project.db analyze .
```

## Auto-configure AI tools

```bash
loom install
```

Detects installed AI tools (Claude Code, Cursor, Windsurf, Codex) and writes MCP config for each. Installs git post-commit hook for incremental sync. Writes `~/.claude/skills/loom.md` so Claude Code agents get workflow instructions automatically.

Target a specific platform:
```bash
loom install --platform claude-code
```

## Start the MCP server

```bash
loom serve
```

Runs in stdio mode. MCP clients connect via the config written by `loom install`. The `loom://primer` resource is available at session start.

Standalone (for `claude mcp add`):
```bash
uvx loom-tool     # runs loom-mcp entry point directly
```

## Session primer

```bash
loom context
```

Prints ~200-token overview: languages, file count, function count, modules by function count, hot functions, summary coverage, last analyzed time.

Drill into one module:
```bash
loom context --module auth
```

JSON output for scripting:
```bash
loom context --json
```

## Search

```bash
loom query "validate token"
```

Uses FTS5 full-text search on name + summary + path. Returns node IDs, paths, kinds, and summaries.

## Call graph

```bash
loom callers "validate_token"
loom callees "validate_token"
loom blast-radius "validate_token" --depth 3
```

Targets can be plain names or full node IDs (`function:src/auth.py:validate_token`).

## Statistics

```bash
loom stats
```

Node and edge counts by kind. Useful for verifying index state.

## Summaries

```bash
loom summaries
loom summaries --limit 50
```

Shows agent-written summaries, most recently updated first. Empty table means no agent has stored understanding yet — auto-summaries exist but are not shown here.

## Communities and dead code

```bash
loom communities    # run Louvain community detection
loom dead-code      # mark functions with no incoming CALLS
```

Both run automatically as part of `loom analyze`. Use these to re-run on demand.

## Incremental sync

```bash
loom sync --old-sha abc123 --new-sha def456
```

SHA-256 driven. Re-parses only changed files between two git SHAs. The git post-commit hook installed by `loom install` calls this automatically on every commit.

## HTML export

```bash
loom export
loom export --output graph.html
```

Generates self-contained interactive HTML graph. Opens in browser.

## MCP config (manual)

If `loom install` doesn't cover your tool, add manually:

**Claude Code / Cursor / Windsurf** (`~/.claude/mcp.json` etc.):
```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["loom-tool"]
    }
  }
}
```

**With custom DB path:**
```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["loom-tool"],
      "env": {
        "LOOM_DB_PATH": "/path/to/project.db"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOOM_DB_PATH` | `~/.loom/loom.db` | SQLite database path |

## Typical workflows

### First-time setup
```bash
pip install loom-tool
cd my-repo
loom analyze .
loom install
loom context    # verify indexing worked
```

### Ongoing development
Post-commit hook fires automatically after every `git commit`. Nothing else needed.

Manual refresh after large changes:
```bash
loom analyze .
```

### Agent integration (Claude Code)
1. `loom install` writes MCP config
2. Start a new Claude Code session
3. Agent calls `start_session()` → gets `session_id`
4. Agent uses `search_code`, `get_context`, `store_understanding`
5. Next session: `get_delta(previous_session_id)` → only changed nodes

## Troubleshooting

### `loom serve` looks stuck
Expected. MCP server stays running and waits for stdio requests from the MCP client.

### `loom analyze` shows 0 files changed
All files match their stored SHA-256. Run is complete — nothing changed since last analyze.

### `search_code` returns no results
Run `loom analyze .` first. If the DB exists but is empty, verify the repo path is correct.

### Summary coverage low
Coverage fills over time as agents call `store_understanding`. Auto-summaries provide ~80% baseline immediately after `loom analyze`.

### Node ID not found in `get_context`
IDs are relative-path-based. Use `search_code` to find the correct ID first.
