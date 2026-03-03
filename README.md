# Loom

> A unified code + document knowledge graph. The foundation for code intelligence.

Loom indexes your **codebase** and your **documentation** into a single connected graph — where code symbols and document sections are linked by meaning, not just proximity. Ask questions that span both worlds simultaneously.

```
$ loom analyze . --docs ./specs/

  Walking code...          142 files, 7 languages
  Parsing AST...           623 symbols extracted
  Tracing calls...         847 edges resolved
  Detecting communities... 8 clusters found
  Walking docs...          3 documents, 47 sections
  Generating summaries...  47 section summaries
  Linking code ↔ docs...   89 IMPLEMENTS edges, 12 SPECIFIES edges
  Generating embeddings... 670 vectors stored

  Done in 8.2s — 670 nodes, 948 edges, 89 cross-domain links
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
pip install loomiq
# or with uv (recommended)
uv add loomiq
```

**Requirements:** Python 3.12+, Docker (for FalkorDB)

```bash
# Start the graph database
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

**Windows users:** use `winloop` instead of `uvloop` — Loom handles this automatically.

---

## Quick start

```bash
# 1. Index your repo + docs
loom analyze . --docs ./specs/

# 2. Ask questions
loom query "how does authentication work?"

# 3. Check blast radius before a change
loom impact validate_user

# 4. Check if your code covers the spec
loom coverage ./specs/requirements.pdf

# 5. Start MCP server (for Claude Code, Cursor, Copilot)
loom serve --watch
```

---

## How it works

Loom builds a property graph in FalkorDB where **code symbols** and **document sections** are both nodes, connected by typed edges.

```
validate_user()  ──[CALLS]──────────▶  hash_password()
validate_user()  ──[IMPLEMENTS]──────▶  §3.2.4 Input Validation
validate_user()  ──[MEMBER_OF]───────▶  community:auth
§3.2.4           ──[CHILD_OF]─────────▶  Chapter 3: Security
```

**The semantic linker** creates the cross-domain edges automatically using a 3-tier approach:
1. **Name matching** — `validate_user` ↔ `User Validation` (free, instant)
2. **Embedding similarity** — nomic-embed-text in a unified code+prose space (local, free)
3. **LLM fallback** — for ambiguous cases only (~10% of links)

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
├── ingest/               # (WIP) source connectors
├── analysis/             # (WIP) analysis pipeline
├── embed/                # (WIP) embeddings
├── linker/               # (WIP) cross-domain linking
├── search/               # (WIP) query/search layer
├── watch/                # (WIP) file watching
├── drift/                # (WIP) drift detection
├── llm/                  # (WIP) LLM client
└── mcp/                  # (WIP) MCP server

tests/
├── unit/
├── integration/
└── fixtures/
```

---

## MCP Tools (for AI agents)

Loom exposes 5 tools via MCP that any compatible AI agent can call:

| Tool | What it returns |
|---|---|
| `loom_query` | Dual-traversal search — code + doc results in one call |
| `loom_context` | Full picture of a symbol: callers, callees, linked specs, community |
| `loom_impact` | Blast radius of a change — depth-grouped, with stale doc sections |
| `loom_coverage` | Requirement coverage score per doc section (0–100%) |
| `loom_drift` | Whether recent code changes potentially violate linked spec sections |

### Claude Code setup

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "loom": {
      "command": "loom",
      "args": ["serve"],
      "env": {
        "LOOM_DB_HOST": "localhost",
        "LOOM_DB_PORT": "6379"
      }
    }
  }
}
```

---

## CLI Reference

```bash
loom analyze <path> [--docs <path>] [--watch]
    Index a repo. Optionally include a docs folder. --watch keeps running.

loom query "<question>"
    Natural language query across code + docs.

loom context <symbol>
    Full context for a code symbol: callers, callees, community, linked specs.

loom impact <symbol>
    Blast radius — everything affected if this symbol changes.

loom coverage <doc_path> [--section <id>]
    Requirement coverage score. Which code implements which spec?

loom watch <path>
    Start watch mode. Re-indexes on file changes, flags drift in real time.

loom serve [--port 8080]
    Start the MCP server for AI agents.

loom config
    Show current configuration (DB host, LLM model, etc.)
```

---

## Configuration

Create `~/.loom/config.toml`:

```toml
[db]
host = "localhost"
port = 6379

[llm]
# Use Ollama locally (free, private):
model = "ollama/llama3.2"

# Or OpenAI (fast, cheap ~$0.05/index run):
# model = "gpt-4o-mini"
# api_key = "sk-..."

# Or Groq (free tier, fast):
# model = "groq/llama-3.2-11b"

[embed]
model = "nomic-ai/nomic-embed-text-v1.5"  # downloaded once, runs locally

[analysis]
git_history_months = 6        # for coupling analysis
community_min_size = 3        # minimum nodes for a community
noise_filter = true           # exclude print(), len(), etc. from call graph
```

Or use environment variables:
```bash
LOOM_LLM_MODEL=ollama/llama3.2
LOOM_DB_HOST=localhost
LOOM_DB_PORT=6379
```

---

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Graph DB | FalkorDB | Redis-based, 6× faster than Neo4j, native vector support |
| Code parsing | tree-sitter | Language-agnostic AST parsing, 7 languages |
| Doc parsing | PyMuPDF + mammoth | 5-10× faster than pdfplumber |
| Embeddings | nomic-embed-text-v1.5 | Unified code+prose space, 8192 ctx, local ONNX |
| LLM | LiteLLM | Any provider (OpenAI, Ollama, Groq) with one config change |
| Communities | igraph + leidenalg | Leiden algorithm, better than Louvain |
| File watching | watchfiles | Rust-based, 500ms debounce |
| MCP server | FastMCP | Official MCP protocol |
| Async | asyncio + winloop/uvloop | Cross-platform, 2-4× faster event loop |
| CLI | Typer + Rich | Clean terminal UI |

---

## Cost

**Building Loom: $0.** Everything runs locally.

- FalkorDB: free, runs in Docker
- Embeddings: local nomic model, no API
- LLM calls: use Ollama locally (free) or OpenAI API (~$0.05/index run)
- All libraries: open source

**Hosting for others:** ~$6/month Hetzner VPS for the first 50 users.

---

## Products built on Loom

Loom is the open-source foundation. Six products are planned on top:

| Product | What it does | Pricing |
|---|---|---|
| **Cortex** | MCP layer — gives AI agents full code+doc context | $49/seat/mo |
| **Review** | Graph-aware PR reviews (CodeRabbit competitor) | $24/seat/mo |
| **Nexus** | Requirements traceability — replaces IBM DOORS | $500/team/mo |
| **Sentinel** | Compliance intelligence (GDPR, SOC2, PCI, HIPAA) | $1K/team/mo |
| **Pulse** | Living architecture docs — auto-updates Confluence | $200/mo add-on |
| **Meridian** | Enterprise platform — federated across 50+ repos | $50K+/year |

---

## Development

```bash
# Clone and set up
git clone https://github.com/YOUR_USERNAME/loom
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
- [ ] Python code parser (tree-sitter)
- [ ] PDF/DOCX/Markdown doc pipeline
- [ ] Semantic linker (3-tier)
- [ ] Dual-traversal search
- [ ] Watch mode + drift detection
- [ ] MCP server (5 tools)
- [ ] CLI

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
