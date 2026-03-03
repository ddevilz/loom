# Technical Capabilities

This document contains implementation-oriented details (parsers, metadata, edges) that are intentionally kept out of the product-oriented README.

## Code parsing (tree-sitter)

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
  - `calls` edges from function/method bodies when resolvable (currently implemented for Python call tracing).
- **Level 4: Dynamic/reflection signals**
  - `dynamic_call`, `reflects_call`, `dynamic_import`, `unresolved_call` edges/pattern metadata for reflective/dynamic invocation.
- **Level 5: Dynamic dispatch (planned)**
  - Candidate resolution for virtual/interface calls with uncertainty.

### Levels implemented (tested)

| Language | L1 Symbols | L2 Metadata | L3 Static calls | L4 Reflection/Dynamic | L5 Dynamic dispatch |
|----------|------------|------------|-----------------|----------------------|--------------------|
| Java | ✅ | ✅ | 🚧 | ✅ | 🚧 |
| TypeScript | ✅ | ✅ | 🚧 | ✅ | 🚧 |
| JavaScript | ✅ | ✅ | 🚧 | ✅ | 🚧 |
| Python | ✅ | ✅ | ✅ | ✅ | 🚧 |

### Supported languages (tested)

| Language | Classes | Functions | Methods | Interfaces | Enums | Types |
|----------|---------|-----------|---------|------------|-------|-------|
| Java | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| TypeScript | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| JavaScript | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Python | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

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

## Tech stack

- Graph DB: FalkorDB
- Parsing: tree-sitter (+ per-language grammars)
- Communities: igraph + leidenalg
- File watching: watchfiles
- LLM provider abstraction: LiteLLM (roadmap-dependent)
