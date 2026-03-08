# Loom Usage Guide

This guide explains how to install, run, query, serve, and maintain Loom in day-to-day use.

## What Loom does

Loom builds a graph of your repository, your documents, and optionally your ticketing data. You can then:

- search the graph semantically
- inspect callers and callees
- trace code to tickets or documents
- monitor a repo continuously with watch mode
- expose the graph to editors and agents over MCP

## Prerequisites

Before using Loom, make sure you have:

- Python 3.12+
- `uv`
- Docker
- FalkorDB running locally or reachable over the configured host/port

Install dependencies:

```bash
uv sync
```

Start FalkorDB:

```bash
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

## Environment configuration

Common environment variables:

```bash
LOOM_DB_HOST=localhost
LOOM_DB_PORT=6379
LOOM_LLM_MODEL=gpt-4o-mini
LOOM_LLM_API_KEY=...
LOOM_JIRA_URL=https://your-domain.atlassian.net
LOOM_JIRA_EMAIL=you@example.com
LOOM_JIRA_API_TOKEN=...
```

Use LLM settings only if you want LLM-backed semantic workflows.

## Basic health check

Verify the CLI imports correctly:

```bash
uv run loom --dev
```

## Index a repository

The main entrypoint is `loom analyze`.

Analyze the current repository:

```bash
uv run loom analyze . --graph-name myrepo --exclude-tests
```

Force a rebuild of the repo-scoped graph state:

```bash
uv run loom analyze . --graph-name myrepo --exclude-tests --force
```

Analyze a specific repo path:

```bash
uv run loom analyze F:\my-repo --graph-name myrepo --exclude-tests
```

What `analyze` does:

- walks the repository
- parses supported files
- creates file and symbol nodes
- extracts structural edges such as `CALLS`
- computes summaries and embeddings
- links code to docs when available
- writes all graph state into FalkorDB

## Analyze with docs

If you have a docs folder:

```bash
uv run loom analyze . --docs ./docs --graph-name myrepo --exclude-tests
```

This lets Loom ingest both code and document nodes into the same graph.

## Analyze with Jira

If you want Jira-backed traceability during indexing:

```bash
uv run loom analyze . \
  --graph-name myrepo \
  --jira-project PROJ \
  --jira-url https://your-domain.atlassian.net \
  --jira-email you@example.com \
  --jira-token <token>
```

## Query the graph

Use `loom query` for semantic search.

```bash
uv run loom query "how is authentication validated" --graph-name myrepo
```

Limit results:

```bash
uv run loom query "entrypoint for API server startup" --graph-name myrepo --limit 5
```

This search uses embeddings and graph expansion, so the results are more semantic than a plain text grep.

## Traceability commands

Use `loom trace` for traceability workflows.

### Unimplemented tickets

```bash
uv run loom trace unimplemented --graph-name myrepo
```

### Untraced functions

```bash
uv run loom trace untraced --graph-name myrepo
```

### Impact of a ticket

```bash
uv run loom trace impact PROJ-123 --graph-name myrepo
```

### Tickets linked to a function

```bash
uv run loom trace tickets function:F:/repo/src/app.py:handler --graph-name myrepo
```

### Sprint coverage

```bash
uv run loom trace coverage sprint-42 --graph-name myrepo
```

## Inspect call relationships

Use `loom calls` to inspect call graph relationships.

### Dump a sample of all call edges

```bash
uv run loom calls --direction dump --graph-name myrepo --limit 20
```

### Show both callers and callees for a function id

```bash
uv run loom calls --target function:F:/repo/src/app.py:handler --direction both --graph-name myrepo
```

### Resolve by plain name

```bash
uv run loom calls --target handler --kind function --direction both --graph-name myrepo
```

## Find likely entrypoints

Use `loom entrypoints` to inspect high-signal root nodes.

```bash
uv run loom entrypoints --graph-name myrepo --limit 30
```

This command combines:

- name-based entrypoint heuristics
- call roots with no incoming `CALLS`
- relationship distribution summaries

## Incremental sync between commits

Use `loom sync` when you want to apply only the changes between two SHAs.

```bash
uv run loom sync \
  --old-sha <old_sha> \
  --new-sha <new_sha> \
  --graph-name myrepo \
  --repo-path .
```

This is useful for commit-to-commit updates, CI workflows, or validating incremental correctness.

## Watch mode

Use `loom watch` to continuously monitor a repository and reindex on file changes.

```bash
uv run loom watch . --graph-name myrepo --debounce 500
```

Important behavior:

- watch mode is mostly silent after startup
- it waits for filesystem changes
- silence does not mean it is stuck

If you want to validate it manually:

1. start `loom watch`
2. create or edit a small file in the repo
3. query Loom for the new symbol or file
4. delete the file and confirm the symbol can no longer be resolved

## Serve Loom over MCP

Use `loom serve` to expose Loom to MCP-capable clients.

```bash
uv run loom serve --graph-name myrepo
```

Loom uses stdio transport for MCP serving.

### Example Windsurf MCP config

```json
{
  "mcpServers": {
    "loom": {
      "command": "uv",
      "args": ["run", "loom", "serve", "--graph-name", "myrepo"],
      "cwd": "F:\\loom"
    }
  }
}
```

Once connected, the MCP client can use Loom tools such as:

- `search_code`
- `get_callers`
- `get_spec`
- `check_drift`
- `get_impact`
- `get_ticket`
- `unimplemented`

## Typical workflows

### Workflow: first-time setup

1. start FalkorDB
2. run `uv sync`
3. run `uv run loom analyze <repo> --graph-name <name>`
4. verify with `loom query` or `loom entrypoints`

### Workflow: ongoing local development

1. run `loom analyze` once for a baseline graph
2. run `loom watch` during local development
3. use `loom query`, `loom calls`, and `loom trace` while working

### Workflow: agent integration

1. index the repository
2. start `loom serve`
3. connect the MCP client
4. use MCP tools to query the graph from the editor or agent

### Workflow: incremental verification

1. analyze the repository into a graph
2. pick two git SHAs
3. run `loom sync --old-sha ... --new-sha ...`
4. verify counts and outputs

## Troubleshooting

### `watch` looks stuck

This is usually expected. Watch mode is quiet after startup and only reacts to file changes.

### `serve` looks stuck

This is also expected. MCP servers stay running and wait for stdio requests.

### `trace` returns no ticket data

Your graph may not contain Jira/doc nodes yet. Run `analyze` with docs or Jira inputs first.

### `query` returns fallback-style results

This can happen if the vector index is unavailable. Search may still work via brute-force fallback, but it will be slower.

### `calls --target <id>` returns no edges

That may mean the node exists but has no callers/callees, not necessarily that the node is missing. If you want resolution validation, use plain-name lookup with `--kind`.

## Related docs

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/TECHNICAL_CAPABILITIES.md`
- `docs/MANUAL_INTERVENTION_ERRORS.md`
