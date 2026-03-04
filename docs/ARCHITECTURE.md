# Loom: Architecture & Codebase Guide

This document explains what the Loom project is trying to achieve, and how the main packages/modules fit together.

It is intentionally **high-level** (module and subsystem oriented) rather than a complete function-by-function reference.

---

## Project goal (what we’re trying to achieve)

Loom is a code/document ingestion and analysis system.

At a high level, Loom:

- Walks a repository (gitignore-aware, safe directory traversal)
- Parses supported files into a uniform internal representation (`Node` objects)
- Extracts relationships between nodes (`Edge` objects), e.g. call graphs
- Stores and queries these nodes/edges in a graph database (FalkorDB)
- Enables downstream analysis (communities/clustering, traversal, similarity search)

The design aim is to:

- Support **multi-language parsing** (tree-sitter based for code languages)
- Treat non-code “markup/config” files as **first-class FILE nodes**
- Keep IDs stable and deterministic so graphs are reproducible
- Be resilient (skip unsupported files, tolerate parse errors)

---

## Key concepts / data model

### `Node` (`loom.core.node`)
A `Node` is the canonical unit of information for both:

- Code symbols (functions/classes/methods/etc.)
- File-level “document” objects (FILE nodes)
- Document structure (doc/section/chapter/etc.)

Important fields:

- `id`: globally unique identifier
- `kind`: enum (`NodeKind`) such as `FUNCTION`, `CLASS`, `FILE`, etc.
- `source`: `CODE` vs `DOC`
- `name`, `path`: human-friendly identifiers
- `start_line`, `end_line`, `language`: code-only metadata
- `metadata`: extensible dictionary for extracted facts (framework hints, Rails DSL, etc.)

ID conventions:

- Code nodes: `<kind.value>:<path>:<symbol>`
  - Produced by `Node.make_code_id(kind, path, symbol)`
- Doc nodes: `doc:<doc_path>:<section_ref>`
  - Produced by `Node.make_doc_id(doc_path, section_ref)`

### `Edge` + `EdgeType` (`loom.core.edge`)
An `Edge` links two nodes.

Typical examples:

- `CALLS`: function A calls function B
- additional edge types exist for structural and “dynamic/reflection” relationships

Edges can carry:

- `confidence`: float that can encode heuristic strength
- `metadata`: e.g. `{unresolved: true, ambiguous: true}`

### Graph storage (`loom.core.graph` + `loom.core.falkor.*`)
Graph persistence is via FalkorDB.

- Nodes are stored as `(:Node { ...props... })` plus an additional per-kind label, e.g. `(:Function)`
- Edges are stored as relationships between nodes
- Schema initialization creates property indexes and a vector index on `Node.embedding` for similarity search

---

## Parsing pipeline (end-to-end)

The core “ingest code” pipeline is in `loom.analysis.code.parser`:

1. **`parse_repo(root)`**
   - If `root` is a file → delegates to `parse_code(root)`
   - If `root` is a directory:
     - Calls `walk_repo(root)` to discover files (gitignore-aware)
     - For each discovered file, calls `parse_code(file)`
     - Aggregates and returns a single flat list of `Node`s

2. **`walk_repo(root)`** (`loom.ingest.code.walker`)
   - Uses root-level `.gitignore` via `pathspec`
   - Skips default directories (`DEFAULT_SKIP_DIRS`), hidden directories, and symlinked directories
   - Groups results by language
   - Special-cases `.env*` files by **filename prefix** because suffix-based extension logic can be misleading

3. **`parse_code(path)`** (`loom.analysis.code.parser`)
   - Converts `path` to a `Path` and determines the extension
   - Special-cases `.env*` by forcing the logical extension to `.env`
   - Uses `LanguageRegistry` to decide whether to skip and which parser to call

4. **Language parsers** (`loom.ingest.code.languages.*`)
   - Code languages typically use tree-sitter to extract functions/classes/etc.
   - Markup/config parsers create a `FILE` node with metadata rather than symbol extraction

---

## `parse_tree()` vs `parse_repo()` (why there are two)

Both live in `loom.analysis.code.parser`.

### `parse_repo(root, exclude_tests=False)`
This is the **authoritative** repo parser.

What it does:

- Uses `walk_repo()` for discovery (gitignore-aware, symlink-safe)
- Delegates each file to `parse_code()` which delegates to the language registry
- Returns a flat `list[Node]`
- Logs how many files were parsed and how many nodes were produced

When to use it:

- **Always prefer this** for real ingestion and analysis.

### `parse_tree(root, exclude_tests=False)`
This is a **backward-compatible wrapper**.

What it does:

- Emits a `DeprecationWarning`
- Immediately delegates to `parse_repo()`

Why it exists:

- To preserve older call sites/tests that still call `parse_tree()`
- To provide a gentle migration path while encouraging `parse_repo()`

The name `parse_tree()` is misleading now:

- It does not return a tree
- It returns the same flat `list[Node]` as `parse_repo()`

---

## LanguageRegistry (extension → parser mapping)

Module: `loom.ingest.code.registry`

Responsibilities:

- Maintain `extension -> parser` mapping
- Decide which files/dirs to skip

Key behaviors:

- `should_skip_dir(dirname)`:
  - skips hidden dirs and configured skip dirs
- `should_skip_file(extension)`:
  - skips known unparseable extensions
  - skips extensions not registered
- `_register_defaults(reg)`:
  - registers code languages (py/ts/js/go/java/rust/ruby)
  - registers markup/config languages (html/xml/json/css/yaml/properties/toml/ini/env)

---

## Call graph extraction (Python)

Module: `loom.analysis.code.calls`

Responsibilities:

- Parse a Python file with tree-sitter
- Extract call sites from function bodies
- Resolve call targets against known symbols
- Create `EdgeType.CALLS` edges

Important details:

- `_extract_call_name()` assigns a name + confidence based on how direct the call is:
  - `foo()` is high confidence
  - `obj.foo()` is slightly lower
  - computed calls (dynamic) become unresolved
- `trace_calls()` accepts `all_symbols: dict[str, list[Node]]` to avoid collisions when multiple methods share the same name
- Ambiguity resolution heuristics:
  - Prefer same-file candidates
  - Prefer `FUNCTION` over `METHOD` if it yields a single match
  - Otherwise mark unresolved/ambiguous

---

## Graph API and repositories

### `LoomGraph` (`loom.core.graph`)
High-level async API around FalkorDB:

- Initializes schema
- Provides node/edge CRUD + bulk insert
- Provides traversal (`neighbors`)
- Provides `delete()` to clear graph contents (used for test isolation)

### Falkor gateway + repositories (`loom.core.falkor.*`)

- `gateway.py`: low-level DB connection and query execution
- `schema.py`: index creation, vector index creation, and idempotency handling
- `repositories.py`:
  - `NodeRepository`: upsert/get/delete/bulk_upsert
  - `EdgeRepository`: upsert + **chunked** bulk_upsert to avoid OOM/timeouts
  - `TraversalRepository`: neighbor traversal in steps
- `queries.py`: centralized cypher templates

---

## Development utilities

Module: `loom.devtools`

- `check_deps()`: verify declared dependencies are installed
- `run_tests()`: runs tests via `unittest` discovery

Note: In this repo, tests are primarily run with `pytest` (via `uv run pytest ...`).

---

## Where to start (entrypoints)

- CLI entrypoint: `loom.cli:main`
- Primary parsing APIs:
  - `loom.analysis.code.parser.parse_repo()`
  - `loom.analysis.code.parser.parse_code()`
- Graph API:
  - `loom.core.graph.LoomGraph`

---

## Glossary

- **Ingest**: discover + parse files into `Node`s
- **Analysis**: compute relationships/communities/embeddings over those nodes
- **FalkorDB**: graph database used for persistence and traversal
- **tree-sitter**: incremental parser used for multi-language AST extraction
