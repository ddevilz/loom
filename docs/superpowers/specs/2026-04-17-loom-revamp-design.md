# Loom Revamp Design

**Date:** 2026-04-17  
**Status:** Approved  
**Scope:** Full structural + code quality revamp. Option B (Structural Revamp) + git-commit linker replacement.

---

## Goals

1. **Ship faster** — eliminate duplication so feature work is cheap
2. **Reliability** — fill FalkorDB infra test gaps, harden error paths
3. **Onboarding** — clear module boundaries, no mystery files
4. **Correct linking** — replace noisy embedding-based Jira linker with deterministic git-commit linker

---

## Part 1: CLI Domain Split

### Problem
`cli.py` at 1,165 lines handles 10+ commands, 6 formatting functions, and query execution — violates single responsibility.

### Solution
Split into domain modules:

```
src/loom/cli/
├── __init__.py       # Typer app + subgroup registration, entry point
├── graph.py          # query, trace, calls, blast_radius, entrypoints
├── ingest.py         # index, sync, watch, enrich
├── analysis.py       # analyze, tickets, drift
└── formatters.py     # _render_table, _print_call_rows, all display helpers
```

### Rules
- `formatters.py` has zero imports from other `cli/` modules (no cycles)
- Each domain module imports from `formatters`, never from sibling domain modules
- `__init__.py` registers all three subgroups into the root Typer app

---

## Part 2: Language Parser Base Class

### Problem
7 language parsers each implement `_Context` class and `parse_code()` scaffold with repeated boilerplate (~60% duplication).

### Solution
Extract shared logic to `ingest/code/languages/_base.py`:

```python
@dataclass
class _BaseContext:
    class_stack: list[str] = field(default_factory=list)
    fn_stack: list[str] = field(default_factory=list)

    def push_class(self, name: str) -> None: ...
    def pop_class(self) -> None: ...          # no-op + warning if empty, never raises
    def current_class(self) -> str | None: ...
    def push_fn(self, name: str) -> None: ...
    def pop_fn(self) -> None: ...             # no-op + warning if empty, never raises
    def current_fn(self) -> str | None: ...
    def qualified_name(self) -> str: ...      # "ClassName.method_name"

class _BaseParser:
    language: ClassVar[str]
    node_type_map: ClassVar[dict[str, NodeKind]]  # tree-sitter type → NodeKind

    def parse_code(self, source: str, file_path: str) -> list[Node]: ...
    def _walk(self, tree, ctx: _BaseContext, nodes: list[Node]) -> None: ...
    # abstract: _handle_node(node, ctx, nodes) — language overrides this
```

Each of 7 parsers becomes: node type mappings + `_handle_node` overrides only.

---

## Part 3: Call Extractor Consolidation

### Problem
Three separate call extractors (`calls.py`, `calls_ts.py`, `calls_java.py`) share identical BFS traversal logic with language-specific node type checks inlined.

### Solution
Package with shared traversal core:

```
analysis/code/calls/
├── __init__.py       # public API: extract_calls(nodes, language) → list[Edge]
├── _base.py          # shared AST walk, call resolution, deduplication
├── python.py         # CALL_NODE_TYPES, resolve_callee() for Python AST
├── typescript.py     # TS/JS-specific call patterns
└── java.py           # Java-specific call patterns
```

Public API contract: `extract_calls(nodes: list[Node], language: str) -> list[Edge]`  
Callers don't know which adapter runs.

---

## Part 4: Vestigial File Deletion

Delete 4 files, inline content. All cross-file import chains must be updated in the same commit.

| File | Destination | Notes |
|---|---|---|
| `ingest/helpers.py` (36L) | `file_node_id()`, `make_file_node()`, `build_contains_edges()` → `ingest/pipeline.py` | Only used by pipeline + incremental; both get updated |
| `ingest/result.py` (56L) | `IndexResult`, `IndexError`, `IndexPhase`, `append_index_error()` → `ingest/pipeline.py` | Used by `pipeline.py` and `incremental.py`; both imports updated |
| `llm/client.py` (32L) | Delete; callers use `litellm.acompletion()` directly | Handled as part of linker slim-down in Part 6 |
| `core/protocols.py` (32L) | All 4 protocols (`QueryGraph`, `BulkGraph`, `EdgeWriteGraph`, `NeighborGraph`) → `core/types.py` (new file) | Not into `gateway.py` — that is a connection wrapper. `types.py` is the correct home for interface definitions |

**`core/types.py`** (new): Contains only protocol/interface definitions. No implementation. Replaces `core/protocols.py`. All existing imports of `core.protocols` updated to `core.types`.

---

## Part 5: Semantic Linker Slim-Down (run BEFORE Part 6)

**Important:** This step runs before building the git linker so `pipeline.py` imports remain valid throughout.

### Delete from `linker/`
- `llm_match.py` — LLM matching, expensive, noisy
- `name_match.py` — 60% token overlap threshold too loose, produces false positives
- `reranker.py` — only needed for LLM path
- `prompts.py` — only needed for LLM path

Before deleting, remove all imports and call sites from `linker.py` and `pipeline.py`.

### Slim `linker/linker.py` to embed-only (~40L)
- Raise embed threshold 0.75 → 0.85 (controlled via `LOOM_EMBED_THRESHOLD` in config)
- Match only `NodeSource.DOC` markdown nodes to code nodes (not Jira nodes — Jira linking moves to git)
- Remove LLM fallback path entirely
- Make `SemanticLinker.link()` async; internal CPU-bound embed steps run via `asyncio.to_thread()`

### Remove dead edge type
Delete `EdgeType.LOOM_SPECIFIES` from `core/edge.py` — it was defined but never written anywhere in the codebase.

---

## Part 6: Git-Commit Linker (builds on Part 5)

### Problem
Current Jira linking creates `IMPLEMENTS` edges via embedding similarity — noisy and unreliable. Real relationship is: commit message references ticket ID → changed functions implement that ticket.

### Solution: `ingest/git_linker.py`

```python
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

def link_commits_to_tickets(
    repo_path: Path,
    graph: LoomGraph,
    since_sha: str | None = None,
) -> list[Edge]:
    """
    Walk git log. For each commit:
      1. Extract ticket IDs from commit message via TICKET_RE.
      2. Get changed files from diff.
      3. Resolve changed files → code nodes in graph.
      4. Create IMPLEMENTS edges: code_node → jira_ticket_node.
    
    If no ticket IDs are found in the entire walked range, emit a
    WARNING log: "git_linker: no ticket IDs found in commit range —
    ensure commit messages reference Jira keys (e.g. PROJ-123)."
    
    Returns empty list (not error) for repos with no ticket conventions.
    """
```

### Edge schema additions
`EdgeOrigin.GIT_COMMIT` added to `core/edge.py` `EdgeOrigin` enum — highest trust tier, never overwritten by `EMBED_MATCH`.

Commit metadata stored in the existing `Edge.metadata` dict field:
```python
metadata={
    "commit_sha": "abc123",
    "author": "dev@example.com",
    "timestamp": "2026-04-17T10:00:00Z",
}
```

`core/falkor/mappers.py` updated to serialize/deserialize `EdgeOrigin.GIT_COMMIT` and the new metadata keys. No new Edge fields needed — `metadata: dict` already exists.

### Wire into pipeline
- `index_repo()` calls `link_commits_to_tickets()` after Jira nodes are fetched
- At end of `index_repo()`, write a well-known metadata node to the graph:
  ```cypher
  MERGE (m:_LoomMeta {key: "repo_path"}) SET m.value = $repo_path
  ```
  This persists the repo root so the MCP server can retrieve it without CLI access.
- `sync_repo()` calls with `since_sha=last_indexed_sha`
- `mcp/server.py`: `relink()` tool updated — new signature:

```python
@mcp.tool()
async def relink(
    repo_path: str | None = None,
    embedding_threshold: float = 0.85,
) -> dict:
    """Re-run all linking passes: embed match for docs, git-commit for Jira tickets.
    
    repo_path: path to indexed repo. If omitted, reads from _LoomMeta graph node
    written during index_repo(). Raises ValueError if neither is available.
    """
```

Resolution order for `repo_path`:
1. Use explicit `repo_path` argument if provided
2. Query `MATCH (m:_LoomMeta {key: "repo_path"}) RETURN m.value` from graph
3. If neither available: raise `ValueError("repo_path required — index the repo first")`

`name_threshold` parameter removed (name-based matching deleted).

### Fallback behavior
- Repos with no Jira-style commit messages: `link_commits_to_tickets()` returns `[]`, logs warning. No error raised. Embedding-based doc linking still runs.
- `unimplemented_tickets()` query result should be interpreted in context of whether git linking is active (add note to MCP tool docstring).

### Traceability after change

| Query | Before | After |
|---|---|---|
| `impact_of_ticket("PROJ-123")` | ~60% accurate (embedding noise) | Exact — only functions in commits referencing PROJ-123 |
| `sprint_code_coverage(sprint)` | Approximate | Deterministic |
| `unimplemented_tickets()` | Many false negatives | Real gaps only (for repos using ticket IDs in commits) |

---

## Part 7: Code Quality Revamps

### 7a. Pipeline — explicit `BatchResult`
Replace silent per-file error swallowing:
```python
@dataclass
class BatchResult:
    ok: list[Node]
    failed: list[tuple[Path, Exception]]
```
Callers log `failed` explicitly. Run never stops on one bad file.

### 7b. Cypher builder — parameterized queries
Replace f-string Cypher construction with FalkorDB param dicts everywhere:
```python
# Before
f"MATCH (n) WHERE n.id = '{node_id}'"
# After  
("MATCH (n) WHERE n.id = $id", {"id": node_id})
```
Eliminates injection risk. Makes unit tests deterministic (assert on params dict, not string).

### 7c. Config — finish threshold externalisation
All inline threshold constants move to `config.py` with env var overrides:
- `LOOM_EMBED_THRESHOLD` (default 0.85)
- `LOOM_BLAST_RADIUS_MAX_DEPTH` (default 10)
- Validation: raise on invalid values at startup, not at query time

### 7d. `blast_radius.py` — depth cap + cycle guard
```python
def blast_radius(start_id: str, max_depth: int = 10) -> BlastRadiusPayload:
    visited: set[str] = set()
    # BFS with visited check + depth counter
```
Prevents infinite loop on cyclic call graphs. `max_depth` pulled from config.

### 7e. `gateway.py` — connection retry with backoff
```python
for attempt, delay in enumerate([1, 2, 4]):
    try:
        return FalkorDB(host=..., port=...)
    except ConnectionError:
        if attempt == 2: raise
        time.sleep(delay)
```
Survives Docker startup race.

---

## Part 8: Test Coverage

### Unit tests (no FalkorDB needed)
- `tests/unit/test_cypher_builders.py` — parameterized query construction, assert on `(query_str, params_dict)` tuples
- `tests/unit/test_git_linker.py` — mock `gitpython` repo, test:
  - ticket ID regex extraction from commit messages
  - commit → node mapping (happy path)
  - **zero-match repo: commits with no ticket IDs → returns `[]` + warning logged**
  - incremental: `since_sha` filters to correct commit range
- `tests/unit/test_batch_result.py` — `BatchResult` accumulation, error surfacing
- `tests/unit/test_base_parser.py` — `_BaseContext` push/pop/qualified_name, pop-on-empty no-op
- `tests/unit/test_blast_radius_depth.py` — depth cap stops BFS, cycle guard prevents infinite loop

### Integration tests (require FalkorDB, `@pytest.mark.integration`)
- `tests/integration/test_schema_init.py` — full DDL round-trip, idempotent re-run
- `tests/integration/test_gateway_retry.py` — connection refused → retry → succeed

---

## Correct Implementation Sequence

Steps ordered so each step has its dependencies satisfied:

1. **Delete vestigial files** (`helpers.py`, `result.py`, `protocols.py`) + create `core/types.py` + fix all imports
2. **Extract `_BaseContext` / `_BaseParser`** → update 7 parsers to use base
3. **Consolidate call extractors** into `calls/` package
4. **CLI domain split** — `cli.py` → `cli/` package
5. **Slim linker** — delete `llm_match.py`, `name_match.py`, `reranker.py`, `prompts.py`; slim `linker.py`; delete `llm/client.py`; remove `LOOM_SPECIFIES` edge type
6. **Build `git_linker.py`** — add `EdgeOrigin.GIT_COMMIT`, update `mappers.py`, wire into `pipeline.py` and `sync`
7. **Update `relink()` MCP tool** — new signature, git pass integration
8. **Cypher parameterization** + **`BatchResult`**
9. **`blast_radius` depth cap** + **`gateway` retry** + **config thresholds**
10. **Add unit + integration tests**
11. **Full suite green** — `pytest tests/ -v`, `mypy loom/`, `ruff check loom/`

---

## File Delta Summary (Corrected)

| Action | Files | Approx line change |
|---|---|---|
| Delete | `helpers.py`, `result.py`, `llm/client.py`, `protocols.py`, `llm_match.py`, `name_match.py`, `reranker.py`, `prompts.py` | -490L |
| Split | `cli.py` → `cli/` package | ~0 (reorganize) |
| Extract | `_base.py` parsers, `calls/` package | -200L net (shared code extracted, adapters slimmed) |
| Add | `git_linker.py`, `core/types.py`, 7 test files | +500L |
| Slim | `linker.py` 94L → 40L | -54L |
| **Net** | | **~-250L** (code quality improvement, not line-count competition) |

The primary gain is eliminating duplication and wrong abstractions — not raw line reduction.
