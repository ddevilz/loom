# Loom — Claude Code Context

This file tells Claude Code everything it needs to know to work effectively in this repo.
Read this before touching any file.

---

## What this project is

Loom is a **unified code + document knowledge graph**. It reads a codebase (via tree-sitter AST parsing) and documentation files (PDFs, DOCX, Markdown, Confluence) and stores everything as nodes and edges in FalkorDB — a graph database.

The key innovation: **code symbols and document sections are the same node type**, connected by semantic edges (`IMPLEMENTS`, `SPECIFIES`, `VIOLATES`). This enables queries like "does checkout_flow() satisfy PCI-DSS §3.4?" — something no existing tool can answer.

---

## Architecture — read this first

```
src/loom/
├── core/        ← START HERE. Node, Edge, Graph. Every module uses these.
├── ingest/      ← Source connectors. Code repos + doc files → raw data.
├── analysis/    ← Intelligence. AST parsing, call tracing, communities, summaries.
├── embed/       ← nomic-embed-text (unified embedding space for code AND docs).
├── linker/      ← THE CORE INNOVATION. Creates IMPLEMENTS edges between code+docs.
├── search/      ← Dual-traversal search across code graph + doc tree.
├── watch/       ← watchfiles-based incremental re-indexer.
├── drift/       ← Detects spec violations when code changes.
├── llm/         ← LiteLLM wrapper. Routes to Ollama, OpenAI, Groq etc.
└── mcp/         ← FastMCP server. 5 tools for Claude Code/Cursor/Copilot.
```

**Dependency flow:** `core` ← `ingest` ← `analysis` ← `embed` ← `linker` ← `search/watch/drift` ← `mcp`

Never import from a downstream module into an upstream one. `core` has zero internal imports.

---

## The data model — understand this deeply

Everything is a `Node` or an `Edge`. That's it.

```python
# A function in code:
Node(id="function:src/auth.py:validate_user", kind=NodeKind.FUNCTION, source=NodeSource.CODE, ...)

# A section in a spec document:
Node(id="doc:specs/auth.pdf:3.2.4", kind=NodeKind.SECTION, source=NodeSource.DOC, ...)

# The link between them (created by SemanticLinker):
Edge(from_id="function:src/auth.py:validate_user",
     to_id="doc:specs/auth.pdf:3.2.4",
     kind=EdgeType.LOOM_IMPLEMENTS,
     confidence=0.87,
     link_method="embed_match")
```

**Node ID convention — never break this:**
- Code: `"{kind}:{file_path}:{symbol_name}"` → `"function:src/auth.py:validate_user"`
- Doc: `"doc:{doc_path}:{section_id}"` → `"doc:specs/auth.pdf:chapter_3.2.4"`

---

## Tech stack — key decisions

| What | Tool | Why it matters |
|---|---|---|
| Graph DB | FalkorDB | Redis-based. Run: `docker compose up -d`. Port 6379. |
| Embeddings | fastembed + nomic-embed-text-v1.5 | Local ONNX, no API key, 768-dim, works for both code and prose |
| LLM | LiteLLM | `LOOM_LLM_MODEL=ollama/llama3.2` for local/free, `gpt-4o-mini` for fast |
| Code parsing | tree-sitter | AST-based. Never use regex to parse code. |
| Async | asyncio + winloop (Windows) / uvloop (Linux/Mac) | See platform check in `src/loom/__init__.py` |
| Communities | igraph + leidenalg | Leiden algorithm on the call graph |
| File watching | watchfiles | Rust-based, 500ms debounce |
| MCP | FastMCP | `@mcp.tool()` decorator pattern |

**Windows note:** uvloop doesn't support Windows. We use winloop instead. The platform check in `config.py` handles this automatically — don't remove it.

---

## Environment setup

```bash
# 1. Install dependencies
uv sync

# 2. Start FalkorDB
docker compose up -d

# 3. Copy env file
cp .env.example .env

# 4. Set your LLM (use Ollama for free local inference):
# LOOM_LLM_MODEL=ollama/llama3.2
# or:
# LOOM_LLM_MODEL=gpt-4o-mini
# LOOM_LLM_API_KEY=sk-...

# 5. Run tests
uv run pytest

# 6. Verify graph connection
uv run python scripts/check_env.py
```

---

## Running Loom

```bash
# Index a repo
uv run loom analyze /path/to/repo --docs /path/to/docs

# Query
uv run loom query "how does authentication work?"

# Start MCP server
uv run loom serve

# Watch mode
uv run loom watch /path/to/repo
```

---

## Coding conventions

**Async everywhere.** All I/O — graph queries, LLM calls, file reads — must be async. Use `asyncio.gather()` for concurrent operations. Never `time.sleep()` — always `await asyncio.sleep()`.

**Semaphore for LLM calls.** Always wrap concurrent LLM calls with a semaphore:
```python
sem = asyncio.Semaphore(10)
async def call_with_limit(prompt):
    async with sem:
        return await llm.complete(prompt)
results = await asyncio.gather(*[call_with_limit(p) for p in prompts])
```

**MERGE not CREATE in FalkorDB.** Re-indexing must be idempotent. Always:
```cypher
MERGE (n:Node {id: $id}) SET n += $props
```
Never `CREATE` a node directly — it will create duplicates on re-index.

**Bulk over N+1.** Never loop individual FalkorDB inserts. Always `UNWIND`:
```python
graph.query("UNWIND $nodes AS n MERGE (node:Node {id: n.id}) SET node += n",
            {"nodes": [n.model_dump() for n in nodes]})
```

**LiteLLM for all LLM calls.** Never call OpenAI/Anthropic SDKs directly. Always go through `src/loom/llm/client.py` which wraps LiteLLM. This ensures Ollama/Groq/OpenAI all work with one config change.

**Pydantic v2.** All data models use Pydantic v2 `BaseModel`. Use `model_dump()` and `model_validate()`. Never use `.dict()` (v1 API).

**Type hints everywhere.** Every function must have complete type hints. `mypy --strict` must pass.

---

## Testing

```bash
uv run pytest                          # all tests
uv run pytest tests/unit/              # unit tests only (no DB needed)
uv run pytest tests/integration/       # integration tests (requires Docker)
uv run pytest --cov=loom               # with coverage
uv run pytest -k "test_node"           # specific test
```

**Test fixtures are in `tests/fixtures/`.**
- `sample_graph.py` — 15 nodes, 20 edges, a realistic auth module. Reuse this everywhere.
- `sample_repo/auth.py` — the Python file the parser tests run against.
- `sample_docs/sample_spec.pdf` — the PDF the doc pipeline tests run against.

**Integration tests require FalkorDB running.** They're marked with `@pytest.mark.integration` and skipped if the DB is unreachable.

---

## Current sprint: Sprint 1 — Graph Foundation

**What we're building right now:**

| Ticket | File | Status |
|---|---|---|
| LOOM-001 | Project init | ✅ Done |
| LOOM-002 | Dependencies + env | ✅ Done |
| LOOM-003 | `src/loom/core/node.py` | 🔄 In progress |
| LOOM-004 | `src/loom/core/edge.py` | ⬜ Todo |
| LOOM-005 | `src/loom/core/graph.py` | ⬜ Todo |
| LOOM-006 | `src/loom/core/schema.py` | ⬜ Todo |
| LOOM-007 | E2E test | ⬜ Todo |

**Sprint goal:** `pytest tests/integration/test_graph_e2e.py` passes cleanly.

---

## What NOT to do

- **Don't use regex to parse code.** tree-sitter exists for this. Regex breaks on nested structures.
- **Don't call LLM APIs directly.** Always use `src/loom/llm/client.py`.
- **Don't touch FalkorDB directly** outside of `src/loom/core/graph.py`. All DB access through `LoomGraph`.
- **Don't create duplicate node IDs.** The ID convention is strict — use `MERGE`.
- **Don't add uvloop directly on Windows.** Use the platform check in config.
- **Don't run LLM calls sequentially in a loop.** Always `asyncio.gather()` with semaphore.
- **Don't hardcode the LLM model.** Always read from config/env.

---

## Key algorithms (planned for v0.2+)

These are NOT implemented yet but are planned. Don't implement them in v0.1:

- **Personalized PageRank** (igraph) — for impact scoring instead of BFS
- **Cross-encoder reranking** (sentence-transformers) — for better linker precision
- **GumTree AST diffing** — for precise drift detection
- **RAPTOR hierarchical summaries** — for multi-level doc intelligence
- **HippoRAG search** — PPR-based retrieval over the unified graph

---

## Getting help

- Architecture decisions → see `docs/architecture.md`
- Ticket details → GitHub Issues (LOOM-XXX labels)
- Graph queries → see `docs/cypher-examples.md`
- LLM prompts used in the linker → see `src/loom/linker/prompts.py`
