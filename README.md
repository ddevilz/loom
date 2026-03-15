# Loom

> A code intelligence platform that turns repositories, docs, and ticket data into one graph you can search, trace, and serve to agents.

Loom ingests source code, technical docs, and optional Jira-style work items into a shared graph stored in FalkorDB. It extracts code structure, builds call relationships, links code to documentation semantically, and exposes the resulting graph through a CLI and MCP server.

## What Loom is

Loom is built for teams that want more than grep, static tags, or disconnected docs. It answers questions like:

- **Where is this requirement implemented?**
- **Which functions call this API?**
- **What changed between two commits, structurally and semantically?**
- **Which code nodes have no traceability to tickets or specs?**
- **What should an agent know about this repo before making a change?**

Loom works by treating code symbols, files, docs, sections, communities, and relationships as graph entities instead of isolated text blobs.

## What problem it solves

In most codebases:

- **Code and docs drift apart**
- **Call relationships are hard to inspect at repo scale**
- **Requirements and implementation links are tribal knowledge**
- **Incremental updates silently lose context in weak indexing systems**
- **AI tools lack a durable, queryable model of the repo**

Loom gives you a persistent graph model of your system so those relationships can be searched, queried, traversed, and served to tooling.

## Core product capabilities

- **Repository indexing**
  - parses source files into graph nodes and edges
  - persists graph state in FalkorDB

- **Multi-language code understanding**
  - supports Python, TypeScript, TSX, JavaScript, JSX, Java, Go, Rust, Ruby, and multiple markup/config formats

- **Call graph extraction**
  - builds `CALLS` relationships for supported languages

- **Document ingestion**
  - ingests Markdown and PDF files into document/section graphs

- **Jira and traceability workflows**
  - links code to Jira tickets and docs
  - supports queries like unimplemented tickets, impact, and coverage

- **Semantic linking**
  - links code to docs with name matching, embedding similarity, and optional LLM fallback

- **Incremental sync and watch mode**
  - updates graph state from git diffs and filesystem changes

- **Semantic search**
  - supports query-time search over embeddings plus graph expansion

- **MCP server**
  - exposes Loom as a tool server for Windsurf, Claude Code, and other MCP clients

## How Loom models a codebase

Loom stores a graph where nodes can represent:

- **Files**
- **Functions**
- **Methods**
- **Classes / interfaces / enums / types**
- **Documents / chapters / sections / paragraphs**
- **Communities**

And edges can represent relationships like:

- **`CALLS`**
- **`MEMBER_OF`**
- **`LOOM_IMPLEMENTS`**
- **`LOOM_SPECIFIES`**
- **`LOOM_VIOLATES`**
- **`COUPLED_WITH`**

Example:

```text
validate_user()  --CALLS---------> hash_password()
validate_user()  --IMPLEMENTS---> §3.2.4 Input Validation
validate_user()  --MEMBER_OF----> community:auth
§3.2.4           --CHILD_OF-----> Chapter 3: Security
```

## Product workflow

Typical workflow:

1. **Analyze a repository** into a named graph
2. **Enrich** the graph with communities and coupling when needed
3. **Query** the graph semantically
4. **Trace** missing or impacted implementation links
5. **Inspect** callers, callees, and entrypoints
6. **Serve** the graph over MCP to an editor or agent
7. **Watch** the repo or **sync** specific git revisions incrementally

## Installation

### Requirements

- **Python** 3.12+
- **uv** for environment and command execution
- **Docker** for FalkorDB

### Setup

```bash
uv sync
```

Start FalkorDB:

```bash
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

Or, if your repo includes a compose setup:

```bash
docker compose up -d
```

### Configuration

Loom is configured through environment variables.

Common values:

```bash
LOOM_DB_HOST=localhost
LOOM_DB_PORT=6379
LOOM_LLM_MODEL=gpt-4o-mini
LOOM_LLM_API_KEY=...
LOOM_JIRA_URL=https://your-domain.atlassian.net
LOOM_JIRA_EMAIL=you@example.com
LOOM_JIRA_API_TOKEN=...
```

Windows event loop handling is automatic.

## Quick start

Verify the CLI:

```bash
uv run loom --dev
```

Index a repository:

```bash
uv run loom analyze . --graph-name myrepo --exclude-tests
```

Run expensive graph enrichment on an existing graph:

```bash
uv run loom enrich --graph-name myrepo
```

Search the graph:

```bash
uv run loom query "how is auth validated" --graph-name myrepo
```

Inspect untraced functions:

```bash
uv run loom trace untraced --graph-name myrepo
```

Inspect blast radius for a symbol:

```bash
uv run loom blast_radius --node validate_user --graph-name myrepo --depth 3
```

Start the MCP server:

```bash
uv run loom serve --graph-name myrepo
```

## CLI reference

| Command | Purpose | Example |
|---|---|---|
| `loom analyze <path>` | Index a repository and print counts, deltas, and errors. This is the main ingest path. | `uv run loom analyze . --graph-name myrepo --exclude-tests --force` |
| `loom enrich` | Run expensive enrichment passes like community detection and git coupling on an already-indexed graph. | `uv run loom enrich --graph-name myrepo --coupling-months 6` |
| `loom query <text>` | Search indexed nodes semantically using embeddings and graph expansion. | `uv run loom query "how does login work" --graph-name myrepo --limit 10` |
| `loom trace <mode> [target]` | Run traceability workflows like unimplemented, untraced, impact, tickets, and coverage. | `uv run loom trace impact PROJ-123 --graph-name myrepo` |
| `loom calls` | Inspect `CALLS` relationships for a target node or dump a slice of the call graph. | `uv run loom calls --target App --direction both --graph-name myrepo` |
| `loom blast_radius` | Show transitive callers of a node as a dependency tree and flag linked docs at risk. | `uv run loom blast_radius --node validate_user --graph-name myrepo --depth 3` |
| `loom entrypoints` | Show likely entrypoints, call roots, and relationship counts. | `uv run loom entrypoints --graph-name myrepo --limit 30` |
| `loom watch` | Watch the filesystem and incrementally update the graph. | `uv run loom watch . --graph-name myrepo --debounce 500` |
| `loom sync` | Sync changes between two git SHAs into the graph. | `uv run loom sync --old-sha abc --new-sha def --graph-name myrepo --repo-path .` |
| `loom serve` | Start the MCP server over stdio. | `uv run loom serve --graph-name myrepo` |
| `loom --dev` | Verify the package imports correctly. | `uv run loom --dev` |

Example `blast_radius` output:

```text
Blast radius: 6 nodes across 3 hops

link (semantic_linker.py)
├─ SemanticLinker (semantic_linker.py)    ← CALLS
│  └─ ingest_repository (pipeline.py)    ← CALLS
│     └─ Registry (registry.py)    ← CALLS
│        └─ LoomServer (server.py)    ← CALLS
└─ ARCHITECTURE.md    ← IMPLEMENTS (doc at risk)

⚠  ARCHITECTURE.md#semantic-linker requires update if link() signature changes.
```

## MCP integration

Loom exposes an MCP server so agents can query the graph directly.

Example Windsurf MCP config:

```json
{
  "mcpServers": {
    "loom": {
      "command": "uv",
      "args": ["run", "loom", "serve", "--graph-name", "loom_graph"],
      "cwd": "F:\\loom"
    }
  }
}
```

Once connected, MCP clients can use Loom tools such as:

- **`search_code`**
- **`get_callers`**
- **`get_spec`**
- **`check_drift`** (AST drift only)
- **`get_blast_radius`**
- **`get_impact`**
- **`get_ticket`**
- **`unimplemented`**

`get_blast_radius` returns a structured payload with:

- **`root`**
- **`summary`** with `total_nodes` and `hops`
- **`callers`** with `depth`, `parent_id`, and `edge_label`
- **`docs_at_risk`** with doc references and update conditions
- **`warnings`** ready for display

## Architecture overview

```text
src/loom/
├── core/                 # Node/edge models, graph facade, FalkorDB access
├── ingest/               # repo parsing, local docs ingestion, Jira ingestion, incremental sync
├── analysis/             # calls, communities, coupling, static summary extraction
├── embed/                # embeddings and similarity helpers
├── linker/               # semantic linking between code and docs
├── search/               # query-time search over graph state
├── drift/                # AST drift detection
├── watch/                # filesystem-driven incremental updates
└── mcp/                  # MCP server integration
```

For deeper technical details, see:

- `docs/ARCHITECTURE.md`
- `docs/TECHNICAL_CAPABILITIES.md`
- `docs/USAGE.md`

## Development

Clone and set up:

```bash
git clone https://github.com/ddevilz/loom
cd loom
uv sync
```

Run tests:

```bash
uv run pytest
```

Run static checks:

```bash
uv run ruff check .
uv run mypy src/
```

## Current state of the product

Loom already provides:

- **Graph-backed repository indexing**
- **Incremental sync correctness paths**
- **Watch mode**
- **Semantic search**
- **Traceability queries**
- **MCP serving**
- **Local document and Jira ingestion hooks**
- **On-demand enrichment with `loom enrich`**

The project is actively evolving in areas like ranking, semantic linking quality, and operational workflows around the graph.

## Documentation

- `README.md` for product overview
- `docs/USAGE.md` for day-to-day usage
- `docs/ARCHITECTURE.md` for system design
- `docs/TECHNICAL_CAPABILITIES.md` for feature details
- `docs/MANUAL_INTERVENTION_ERRORS.md` for operational troubleshooting

## License

MIT — use it, extend it, and build on top of it.
