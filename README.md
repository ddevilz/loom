# Loom

> A unified code + document knowledge graph. The foundation for code intelligence.

Loom indexes your **codebase** and your **documentation** into a single connected graph — where code symbols and document sections are linked by meaning, not just proximity. Ask questions that span both worlds simultaneously.

```
$ loom analyze . --docs ./specs/

  (example output — illustrative)
```

---

## The problem Loom solves

Every engineering team has the same invisible problem: code and documentation drift apart, and **nobody can see the gap**.

- The spec says `validate()` must return a typed error
- The code returns `None`
- No tool reads both at the same time — so nobody catches it

Loom is the connection layer. It knows that `validate_user()` **implements** `§3.2.4 Input Validation`, that it has 47 callers, and that changing its return type would make that spec section stale. No existing tool can do this.

---

## Install

```bash
# Development install (recommended)
uv sync
```

**Requirements:** Python 3.12+, Docker (for FalkorDB)

```bash
# Start the graph database
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

**Windows users:** use `winloop` instead of `uvloop` — Loom handles this automatically.

Optional configuration via environment variables:

```bash
LOOM_DB_HOST=localhost
LOOM_DB_PORT=6379
LOOM_LLM_MODEL=gpt-4o-mini
LOOM_LLM_API_KEY=...
LOOM_JIRA_URL=https://your-domain.atlassian.net
LOOM_JIRA_EMAIL=you@example.com
LOOM_JIRA_API_TOKEN=...
```

---

## Quick start

```bash
# Verify the CLI is installed and imports
loom --dev

# Index a repo
loom analyze . --graph-name myrepo --exclude-tests

# Search semantically across indexed code + docs
loom query "how is auth validated" --graph-name myrepo

# Inspect Jira/code traceability
loom trace unimplemented --graph-name myrepo
```

---

## CLI

| Command | Purpose | Example |
|---|---|---|
| `loom analyze <path>` | Index a repository into FalkorDB and print a Rich summary (file deltas, node/edge counts, duration). | `loom analyze . --graph-name myrepo --exclude-tests --force` |
| `loom query <text>` | Run semantic search over indexed nodes using embeddings plus graph expansion. | `loom query "how does login work" --graph-name myrepo --limit 10` |
| `loom trace <mode> [target]` | Inspect Jira/code traceability: unimplemented tickets, untraced functions, impact, linked tickets, or sprint coverage. | `loom trace impact PROJ-123 --graph-name myrepo` |
| `loom entrypoints` | Show entrypoint candidates and high-signal call graph summaries (name-based candidates, CALLS roots, relationship type counts). | `loom entrypoints --graph-name myrepo --limit 100` |
| `loom calls` | Inspect `CALLS` edges: who a node calls (callees), who calls a node (callers), or dump a slice of the call graph. | `loom calls --graph-name myrepo --target App --direction both --limit 50` |
| `loom watch` | Watch a repo for filesystem changes and re-index incrementally. | `loom watch . --graph-name myrepo --debounce 500` |
| `loom serve` | Start the MCP server for editor/agent integrations. | `loom serve --graph-name myrepo` |
| `loom sync` | Incrementally sync changes between two git SHAs into the graph using git-diff + node diffing. | `loom sync --old-sha abc --new-sha def --graph-name myrepo --repo-path .` |
| `loom --dev` | Development health check (verifies package import OK). | `loom --dev` |

---

## How it works

Loom builds a property graph in FalkorDB where **code symbols** and **document sections** are both nodes, connected by typed edges.

```
validate_user()  ──[CALLS]──────────▶  hash_password()
validate_user()  ──[IMPLEMENTS]──────▶  §3.2.4 Input Validation
validate_user()  ──[MEMBER_OF]───────▶  community:auth
§3.2.4           ──[CHILD_OF]─────────▶  Chapter 3: Security
```

**Semantic linking**: Loom links code and docs via:
1. **Name matching**
2. **Embedding similarity**
3. **LLM fallback** (optional)

Embeddings are persisted during indexing, community detection runs after indexing, and traceability queries can traverse Jira-linked documentation and code symbols.

---

## Architecture

```
src/loom/
├── core/                 # Core graph domain + FalkorDB facade
│   ├── node.py           # Node model (code symbols + doc sections)
│   ├── edge.py           # Edge model + EdgeType
│   ├── graph.py          # LoomGraph async facade
│   └── falkor/           # FalkorDB data-access implementation details
│       ├── gateway.py    # Connection + low-level query execution
│       ├── repositories.py
│       ├── queries.py
│       ├── mappers.py
│       └── schema.py     # Index + vector index initialization
│
├── ingest/               # code, docs, and Jira ingestion
├── analysis/             # summarization, calls, communities, coupling
├── embed/                # embedding generation + similarity helpers
├── linker/               # cross-domain semantic linking
├── search/               # semantic search layer
├── watch/                # file watching + incremental updates
├── drift/                # drift detection
├── llm/                  # LLM client
├── query/                # traceability queries
└── mcp/                  # MCP server tools

tests/
├── unit/
├── integration/
└── fixtures/
```

---

## What you get today

- **Code indexing** into a graph model (nodes + typed edges)
- **Multi-language parsing** (Java, TypeScript/JavaScript, Python)
- **Config + markup awareness** (e.g. properties/env/json/yaml/html/css metadata)
- **Document + Jira ingestion** for traceability workflows
- **Semantic linking** between code and docs
- **Semantic search** over summaries and embeddings
- **Community detection** with `COMMUNITY` nodes and `MEMBER_OF` edges
- **Watch mode** for live repository updates
- **MCP server** for agent/editor integrations

## Technical details

See:

- `docs/TECHNICAL_CAPABILITIES.md`

---

## Cost

**Building Loom: $0.** Everything runs locally.

- FalkorDB: free, runs in Docker
- Embeddings: local nomic model, no API
- LLM calls: use Ollama locally (free) or OpenAI API (~$0.05/index run)
- All libraries: open source

**Hosting for others:** ~$6/month Hetzner VPS for the first 50 users.

---

## Development

```bash
# Clone and set up
git clone https://github.com/ddevilz/loom
cd loom
uv sync

# Start FalkorDB
docker compose up -d

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=loom --cov-report=term-missing

# Lint
uv run ruff check .
uv run mypy src/
```

---

## Roadmap

**v0.1** *(current sprint)*
- [x] Project setup + environment
- [x] Node + Edge models (graph schema)
- [x] FalkorDB CRUD layer + indexes
- [x] Multi-language code parser (Java, TypeScript, JavaScript, Python)
- [x] Advanced parser features (annotations, imports, decorators, async)
- [x] PDF/Markdown doc pipeline
- [x] Semantic linker (3-tier)
- [x] Dual-traversal search
- [x] Watch mode + drift detection
- [x] MCP server tools
- [x] CLI for analyze/query/trace/calls/entrypoints/sync/watch/serve

**v0.2** *(algorithms sprint)*
- [ ] Personalized PageRank for impact scoring
- [ ] Cross-encoder reranking in linker
- [ ] GumTree-style AST diffing for precise drift

**v0.3**
- [ ] RAPTOR hierarchical doc summaries
- [ ] HippoRAG search
- [ ] Confluence + Notion connectors

---

## License

MIT — use it, build on it, ship products with it.
