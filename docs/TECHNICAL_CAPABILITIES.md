# Technical Capabilities

This document contains implementation-oriented details (parsers, metadata, edges) that are intentionally kept out of the product-oriented README.

## Code parsing

Loom parses source files into nodes (symbols) with file/line locations and metadata.

## Parsing levels

Loom’s extraction is intentionally described in levels so it’s clear *how deep* parsing goes.

- **Level 0: File recognition**
  - Identify supported extensions and create a FILE node (for markup/config parsers).
- **Level 1: Symbol extraction**
  - Classes, functions, methods, interfaces, enums, type aliases (language-dependent).
- **Level 2: Metadata extraction**
  - Language-specific metadata attached to nodes (e.g., Java annotations/modifiers, TS imports/exports, Python decorators/async).
- **Level 3: Call edges (static)**
  - `calls` edges from function/method bodies when resolvable.
- **Level 4: Dynamic/reflection signals**
  - `dynamic_call`, `reflects_call`, `dynamic_import`, `unresolved_call` edges/pattern metadata for reflective/dynamic invocation.
- **Level 5: Dynamic dispatch (planned)**
  - Candidate resolution for virtual/interface calls with uncertainty.

### Levels implemented (tested)

| Language | L1 Symbols | L2 Metadata | L3 Static calls | L4 Reflection/Dynamic | L5 Dynamic dispatch |
|----------|------------|------------|-----------------|----------------------|--------------------|
| Java | ✅ | ✅ | ✅ | ✅ | 🚧 |
| TypeScript | ✅ | ✅ | ✅ | ✅ | 🚧 |
| JavaScript | ✅ | ✅ | ✅ | ✅ | 🚧 |
| Python | ✅ | ✅ | ✅ | ✅ | 🚧 |
| Go | ✅ | ✅ | ❌ | ❌ | ❌ |
| Rust | ✅ | ✅ | ❌ | ❌ | ❌ |
| Ruby | ✅ | ✅ | ❌ | ✅ | ❌ |

### Supported languages (tested)

| Language | Classes | Functions | Methods | Interfaces | Enums | Types |
|----------|---------|-----------|---------|------------|-------|-------|
| Java | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| TypeScript | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| JavaScript | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Python | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Go | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Rust | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Ruby | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |

### Markup and config parsing

Markup and config formats are treated as first-class ingest sources. These typically produce `FILE` nodes with rich metadata instead of symbol graphs.

| Format | Notes |
|--------|-------|
| HTML | title, forms, scripts, stylesheets, template hints |
| XML | structural/file metadata |
| JSON | top-level keys and shape hints |
| CSS | classes, ids, media queries, CSS variables |
| YAML | top-level keys and config hints |
| Properties | keys, counts, profile hints, sensitive key detection |
| ENV | variable names/count, sensitive key detection |
| TOML | project metadata and dependencies where recoverable |
| INI | sections and key counts |

### Parser fixtures / E2E stats (integration tests)

| Fixture | Nodes | Notes |
|--------:|------:|------|
| Java Spring Boot | 73 | Annotations/modifiers/inheritance tested in integration fixtures |
| Vue TSX (TypeScript) | 24+ | Imports/exports, async, enums/interfaces/types tested |
| Python Flask | 72 | Imports, decorators, async tested |

## Call graph resolution

Currently supported:

- Direct function calls
- Method invocations
- Constructor calls

Implemented call tracing backends:

- **Python**
  - tree-sitter-based call extraction with same-file and symbol-name heuristics
- **TypeScript / JavaScript**
  - function, arrow-function, and method call extraction
- **Java**
  - method and constructor invocation extraction

Current limitations:

- cross-file target resolution remains heuristic rather than full type-flow analysis
- dynamic dispatch is not fully modeled
- unresolved or ambiguous calls are intentionally preserved as lower-certainty outcomes

### Dynamic dispatch (planned)

Goal: resolve virtual/interface calls to candidate targets and represent uncertainty.

- Phase 1: type-based candidates (Java/TypeScript)
- Phase 2: flow-based narrowing

Representation:
- CALLS edges annotated with resolution metadata, or UNRESOLVED_CALL when no safe target.

## Reflection / metaprogramming (implemented + tested)

Loom detects reflective/dynamic invocation patterns and preserves raw expressions.

### Edge types

- `DYNAMIC_CALL`
- `REFLECTS_CALL`
- `DYNAMIC_IMPORT`
- `UNRESOLVED_CALL`

### Java patterns

- `Class.forName`, `getMethod/getDeclaredMethod`, `invoke`, `newInstance`, `Proxy.newProxyInstance`, etc.

### Python patterns

- `getattr`, `setattr`, `hasattr`, `delattr`, `__import__`, `importlib.import_module`

### TypeScript/JavaScript patterns

- Dynamic `import()`
- Computed member calls `obj[prop]()`

### Ruby patterns

- Rails-style DSL extraction and reflective framework hints preserved as metadata

### Metadata captured

```json
{
  "reflection_pattern": "getMethod|getattr|dynamic_import",
  "dynamic_target": "methodName",
  "raw_expression": "obj.getClass().getMethod(\"foo\")",
  "call_confidence": "low|medium|high"
}
```

## Configuration + markup parsing (tested)

Loom extracts lightweight metadata from common non-code files:

| File type | Examples | Extracts |
|----------|----------|----------|
| Properties | `application.properties` | keys, counts, spring profile hints, sensitive keys |
| Env | `.env.example` | var names/count, sensitive keys |
| TOML | `pyproject.toml` | project name/version, dependencies (best-effort) |
| INI | `.ini`, `.conf` | sections, key counts |
| HTML | `.html` | title, forms, scripts, stylesheets, template hints |
| CSS | `.css` | classes, ids, media query count, css variables |
| JSON | `package.json`, `tsconfig.json` | top-level keys, type hints |
| YAML | `docker-compose.yml` | top-level keys, type hints |

## Document and external knowledge ingestion

Loom can ingest non-code knowledge into the same graph model used for code.

### Document sources

- **Markdown**
  - hierarchical document, chapter, section, subsection, and paragraph extraction
- **PDF**
  - page-based section extraction

### External systems

- **Jira**
  - issue ingestion into doc-style graph nodes with ticket metadata
  - traceability relinking and stale-edge handling on status changes
- **Confluence**
  - page ingestion via REST
- **Notion**
  - page/database ingestion via REST

## Search and traceability

### Semantic search

Loom search combines:

- query embeddings
- FalkorDB vector search
- brute-force similarity fallback when vector index is unavailable
- graph expansion over `CALLS` and `LOOM_IMPLEMENTS`

### Traceability queries

Built-in query workflows include:

- unimplemented tickets
- untraced functions
- impact of a ticket
- tickets for a function
- sprint code coverage

## Incremental and live update capabilities

### Git-based incremental sync

Loom supports commit-to-commit sync with:

- changed-file detection from git diff
- node-level diffing based on content hashes
- rename-aware human-edge migration
- stale-edge invalidation
- AST drift detection that can emit `LOOM_VIOLATES` edges

### Watch mode

Watch mode supports:

- filesystem monitoring with debounce
- invalidation of stale file-scoped edges
- preservation of human-linked nodes when files are removed
- reindexing of changed files into the active graph

## Graph enrichment

### Summaries

Loom supports multiple summary sources:

- parser-derived static summaries
- docstrings and signatures
- local or remote LLM-backed summarization where configured

### Embeddings

- local embedding generation through `fastembed`
- embedding persistence on graph nodes
- dimension validation against configured schema

### Communities

- Leiden community detection over the code graph
- creation of `COMMUNITY` nodes and `MEMBER_OF` edges

### Coupling

- git co-change analysis to create `COUPLED_WITH` file relationships

### Semantic linker

The linker supports a tiered pipeline:

1. name/token matching
2. embedding similarity
3. optional LLM judgment

Optional reranking can refine embedding-based candidate selection.

## MCP and CLI surface

Loom is available through:

- **Typer CLI**
  - `analyze`, `query`, `trace`, `calls`, `entrypoints`, `watch`, `sync`, `serve`
- **FastMCP server**
  - `search_code`, `get_callers`, `get_spec`, `check_drift`, `get_impact`, `get_ticket`, `unimplemented`

## Tech stack

- Graph DB: FalkorDB
- Parsing: tree-sitter (+ per-language grammars)
- Embeddings: fastembed
- Communities: igraph + leidenalg
- File watching: watchfiles
- MCP: fastmcp
- Validation/data models: pydantic
- CLI: typer + rich
- LLM provider abstraction: LiteLLM
