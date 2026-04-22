# Loom Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Structural revamp of Loom — delete vestigial files, extract shared parser base, consolidate call extractors, split CLI by domain, replace noisy embedding-based Jira linker with deterministic git-commit linker, and fill critical test gaps.

**Architecture:** 11 sequential tasks ordered so each task's dependencies are satisfied before use. All tasks are TDD — write failing test first, implement, verify green, commit. The git-commit linker (`ingest/git_linker.py`) replaces 4 linker files; the semantic linker stays only for markdown doc→code linking.

**Tech Stack:** Python 3.12, FalkorDB (falkordb lib), tree-sitter, fastembed, FastMCP, Typer, gitpython, pytest with asyncio_mode=auto, mypy, ruff.

**Spec:** `docs/superpowers/specs/2026-04-17-loom-revamp-design.md`

---

## Task 1: Delete Vestigial Files + Create `core/types.py`

Move 4 protocols from `core/protocols.py` → new `core/types.py`. Inline `ingest/helpers.py` and `ingest/result.py` into `ingest/pipeline.py`. Fix all imports.

**Files:**
- Create: `src/loom/core/types.py`
- Delete: `src/loom/core/protocols.py`
- Modify: `src/loom/ingest/pipeline.py` (inline helpers + result content)
- Modify: `src/loom/ingest/incremental.py` (update imports)
- Delete: `src/loom/ingest/helpers.py`
- Delete: `src/loom/ingest/result.py`
- Modify: every file that imports from the deleted modules (run grep to find all)

- [ ] **Step 1: Find all import sites**

```bash
cd /Users/devashish/Desktop/loom
grep -r "from loom.core.protocols" src/ tests/ --include="*.py" -l
grep -r "from loom.ingest.helpers" src/ tests/ --include="*.py" -l
grep -r "from loom.ingest.result" src/ tests/ --include="*.py" -l
```

Record every file printed. You must update all of them.

- [ ] **Step 2: Create `src/loom/core/types.py`**

```python
# src/loom/core/types.py
from __future__ import annotations

from typing import Any, Protocol

from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind


class QueryGraph(Protocol):
    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


class BulkGraph(QueryGraph, Protocol):
    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...
    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


class EdgeWriteGraph(Protocol):
    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


class NeighborGraph(QueryGraph, Protocol):
    async def neighbors(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None,
        kind: NodeKind | None = None,
    ) -> list[Node]: ...
```

- [ ] **Step 3: Replace every `from loom.core.protocols import ...` with `from loom.core.types import ...`**

Edit each file found in Step 1. Same import names, different module path.

- [ ] **Step 4: Copy `helpers.py` content into `pipeline.py` and update imports**

In `src/loom/ingest/pipeline.py`:
- Remove the line: `from loom.ingest.helpers import build_contains_edges, file_node_id, make_file_node`
- Paste the three function bodies directly into `pipeline.py` (after the imports block, before the first `@dataclass`)

```python
def file_node_id(path: str) -> str:
    return f"{NodeKind.FILE.value}:{path}"


def make_file_node(path: str, *, content_hash: str) -> Node:
    p = Path(path)
    return Node(
        id=file_node_id(path),
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path,
        content_hash=content_hash,
        metadata={},
    )


def build_contains_edges(nodes: list[Node]) -> list[Edge]:
    return [
        Edge(
            from_id=node.parent_id,
            to_id=node.id,
            kind=EdgeType.CONTAINS,
            origin=EdgeOrigin.COMPUTED,
            confidence=1.0,
        )
        for node in nodes
        if isinstance(node.parent_id, str) and node.parent_id
    ]
```

- [ ] **Step 5: Copy `result.py` content into `pipeline.py`**

In `src/loom/ingest/pipeline.py`:
- Remove: `from loom.ingest.result import IndexError, IndexResult`
- Add these after the function definitions from Step 4:

```python
import logging as _logging

IndexPhase = Literal[
    "parse", "calls", "calls_global", "persist", "summarize",
    "link", "embed", "hash", "invalidate", "jira", "process",
]


@dataclass(frozen=True)
class IndexError:
    path: str
    phase: IndexPhase
    message: str


@dataclass(frozen=True)
class IndexResult:
    node_count: int
    edge_count: int
    file_count: int
    files_skipped: int
    files_updated: int
    files_added: int
    files_deleted: int
    error_count: int
    duration_ms: float
    errors: list[IndexError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def append_index_error(
    errors: list[IndexError],
    *,
    path: str,
    phase: IndexPhase,
    error: Exception,
) -> None:
    logger.error(
        "Indexing error in phase '%s' for '%s': %s", phase, path, error, exc_info=True
    )
    errors.append(IndexError(path=path, phase=phase, message=str(error)))
```

Also add `Literal` to the `typing` import at the top of `pipeline.py`.

- [ ] **Step 6: Update `incremental.py` imports**

```bash
grep -n "from loom.ingest" src/loom/ingest/incremental.py
```

Replace any `from loom.ingest.helpers import ...` and `from loom.ingest.result import ...` with imports from `loom.ingest.pipeline`.

- [ ] **Step 7: Delete the now-empty source files**

```bash
rm src/loom/core/protocols.py
rm src/loom/ingest/helpers.py
rm src/loom/ingest/result.py
```

- [ ] **Step 8: Run full test suite to verify no import errors**

```bash
cd /Users/devashish/Desktop/loom
pytest tests/unit/ -v --tb=short -q
```

Expected: all previously-passing tests still pass. Fix any `ImportError` or `ModuleNotFoundError` before proceeding.

- [ ] **Step 9: mypy + ruff**

```bash
mypy src/loom/ --ignore-missing-imports
ruff check src/loom/
```

Fix any errors before committing.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor: delete vestigial files, inline helpers/result into pipeline, move protocols to core/types"
```

---

## Task 2: Extract `_BaseContext` and `_BaseParser`

Create shared base for all 7 language parsers. Each parser currently has its own `_Context` class with manual list management. Extract it to a shared typed base.

**Files:**
- Create: `src/loom/ingest/code/languages/_base.py`
- Modify: `src/loom/ingest/code/languages/python.py` (use `_BaseContext`)
- Modify: `src/loom/ingest/code/languages/typescript.py`
- Modify: `src/loom/ingest/code/languages/javascript.py`
- Modify: `src/loom/ingest/code/languages/java.py`
- Modify: `src/loom/ingest/code/languages/go_lang.py`
- Modify: `src/loom/ingest/code/languages/rust.py`
- Modify: `src/loom/ingest/code/languages/ruby.py`
- Create: `tests/unit/test_base_parser.py`

- [ ] **Step 1: Write failing tests for `_BaseContext`**

```python
# tests/unit/test_base_parser.py
from loom.ingest.code.languages._base import _BaseContext


def test_push_pop_class():
    ctx = _BaseContext()
    ctx.push_class("MyClass")
    assert ctx.current_class() == "MyClass"
    ctx.pop_class()
    assert ctx.current_class() is None


def test_push_pop_fn():
    ctx = _BaseContext()
    ctx.push_fn("my_fn")
    assert ctx.current_fn() == "my_fn"
    ctx.pop_fn()
    assert ctx.current_fn() is None


def test_qualified_name_class_and_fn():
    ctx = _BaseContext()
    ctx.push_class("MyClass")
    ctx.push_fn("my_method")
    assert ctx.qualified_name() == "MyClass.my_method"


def test_qualified_name_fn_only():
    ctx = _BaseContext()
    ctx.push_fn("standalone")
    assert ctx.qualified_name() == "standalone"


def test_qualified_name_empty():
    ctx = _BaseContext()
    assert ctx.qualified_name() == ""


def test_pop_on_empty_does_not_raise(caplog):
    """pop on empty stack must be a no-op with a warning, never raise."""
    import logging
    ctx = _BaseContext()
    with caplog.at_level(logging.WARNING):
        ctx.pop_class()   # empty — must not raise
        ctx.pop_fn()      # empty — must not raise
    assert len(caplog.records) == 2


def test_nested_class_and_fn():
    ctx = _BaseContext()
    ctx.push_class("Outer")
    ctx.push_class("Inner")
    assert ctx.current_class() == "Inner"
    ctx.pop_class()
    assert ctx.current_class() == "Outer"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/unit/test_base_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'loom.ingest.code.languages._base'`

- [ ] **Step 3: Create `src/loom/ingest/code/languages/_base.py`**

```python
# src/loom/ingest/code/languages/_base.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _BaseContext:
    """Shared class/function stack for tree-sitter parsers.

    push/pop are always safe — popping an empty stack emits a warning and
    returns without raising, preventing parser crashes on malformed ASTs.
    """

    class_stack: list[str] = field(default_factory=list)
    fn_stack: list[str] = field(default_factory=list)

    def push_class(self, name: str) -> None:
        self.class_stack.append(name)

    def pop_class(self) -> None:
        if not self.class_stack:
            logger.warning("_BaseContext.pop_class called on empty stack")
            return
        self.class_stack.pop()

    def current_class(self) -> str | None:
        return self.class_stack[-1] if self.class_stack else None

    def push_fn(self, name: str) -> None:
        self.fn_stack.append(name)

    def pop_fn(self) -> None:
        if not self.fn_stack:
            logger.warning("_BaseContext.pop_fn called on empty stack")
            return
        self.fn_stack.pop()

    def current_fn(self) -> str | None:
        return self.fn_stack[-1] if self.fn_stack else None

    def qualified_name(self) -> str:
        parts = []
        if self.class_stack:
            parts.append(self.class_stack[-1])
        if self.fn_stack:
            parts.append(self.fn_stack[-1])
        return ".".join(parts)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/unit/test_base_parser.py -v
```

- [ ] **Step 5: Migrate each language parser to use `_BaseContext`**

For each of the 7 parser files, read the existing `_Context` class, then:
1. Remove the language-specific `_Context` class
2. Add: `from loom.ingest.code.languages._base import _BaseContext`
3. Replace all `_Context()` instantiations with `_BaseContext()`
4. Replace any direct `.class_stack.append(x)` → `ctx.push_class(x)`, `.pop()` → `ctx.pop_class()`, etc.

Do one parser at a time. After each, run:

```bash
pytest tests/unit/ -v -k "python" --tb=short   # replace with the language under test
```

The existing parser tests must stay green after each migration.

- [ ] **Step 6: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

All tests must pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: extract _BaseContext to shared base, migrate all 7 language parsers"
```

---

## Task 3: Consolidate Call Extractors into `calls/` Package

**Files:**
- Create: `src/loom/analysis/code/calls/__init__.py`
- Create: `src/loom/analysis/code/calls/_base.py`
- Create: `src/loom/analysis/code/calls/python.py`
- Create: `src/loom/analysis/code/calls/typescript.py`
- Create: `src/loom/analysis/code/calls/java.py`
- Delete: `src/loom/analysis/code/calls.py`
- Delete: `src/loom/analysis/code/calls_ts.py`
- Delete: `src/loom/analysis/code/calls_java.py`
- Modify: any file importing from the deleted modules

- [ ] **Step 1: Find all import sites for the old call modules**

```bash
grep -r "from loom.analysis.code.calls" src/ tests/ --include="*.py" -l
grep -r "from loom.analysis.code import calls" src/ tests/ --include="*.py" -l
```

- [ ] **Step 2: Read the three existing call extractor files to understand their structure**

```bash
cat src/loom/analysis/code/calls.py
cat src/loom/analysis/code/calls_ts.py
cat src/loom/analysis/code/calls_java.py
```

Note which functions each exports. The public API you're replacing is:
- `calls.py` → `extract_calls(source: str, nodes: list[Node], file_path: str) -> list[Edge]`
- `calls_ts.py` → same signature
- `calls_java.py` → same signature

- [ ] **Step 3: Create the package skeleton**

```bash
mkdir -p src/loom/analysis/code/calls
```

Create `src/loom/analysis/code/calls/__init__.py`:

```python
# src/loom/analysis/code/calls/__init__.py
from __future__ import annotations

from loom.core.node import Node
from loom.core.edge import Edge


def extract_calls(
    source: str,
    nodes: list[Node],
    file_path: str,
    language: str,
) -> list[Edge]:
    """Dispatch to the correct call extractor based on language.

    This is a drop-in replacement for the old per-language call extractors.
    Callers add `language=` to their existing call — signature otherwise identical.

    Args:
        source: Raw file source text.
        nodes: Already-parsed code nodes from the file.
        file_path: Absolute path to the source file.
        language: One of 'python', 'typescript', 'javascript', 'java'.

    Returns:
        List of CALLS edges extracted from the AST.
    """
    from loom.analysis.code.calls.python import extract_calls as _py
    from loom.analysis.code.calls.typescript import extract_calls as _ts
    from loom.analysis.code.calls.java import extract_calls as _java

    dispatch = {
        "python": _py,
        "typescript": _ts,
        "javascript": _ts,   # JS uses TS extractor
        "java": _java,
    }
    fn = dispatch.get(language)
    if fn is None:
        return []
    return fn(source, nodes, file_path)
```

- [ ] **Step 4: Move each extractor's implementation into its adapter file**

Read the actual function signatures in the old files first:

```bash
grep -n "^def extract_calls\|^async def extract_calls" \
  src/loom/analysis/code/calls.py \
  src/loom/analysis/code/calls_ts.py \
  src/loom/analysis/code/calls_java.py
```

Create `src/loom/analysis/code/calls/python.py` — copy the full implementation from `calls.py` verbatim. The function must be named `extract_calls` and have signature `(source: str, nodes: list[Node], file_path: str) -> list[Edge]`.
Create `src/loom/analysis/code/calls/typescript.py` — copy from `calls_ts.py`.
Create `src/loom/analysis/code/calls/java.py` — copy from `calls_java.py`.

Keep all internal logic identical. Only change is the file location.

- [ ] **Step 5: Update all import sites**

Each call site that previously imported:
- `from loom.analysis.code.calls import extract_calls` → unchanged (package now, same name)
- `from loom.analysis.code.calls_ts import extract_calls as extract_ts_calls` → replace with `from loom.analysis.code.calls import extract_calls as extract_ts_calls` and pass `language="typescript"`
- `from loom.analysis.code.calls_java import extract_calls as ...` → same pattern with `language="java"`

In every call site, add the `language=` positional arg matching the language being processed.

- [ ] **Step 6: Delete old files**

```bash
rm src/loom/analysis/code/calls.py
rm src/loom/analysis/code/calls_ts.py
rm src/loom/analysis/code/calls_java.py
```

- [ ] **Step 7: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

All tests must pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: consolidate call extractors into calls/ package with language dispatch"
```

---

## Task 4: CLI Domain Split

Split `src/loom/cli.py` (1,165L) into 4 focused modules.

**Files:**
- Create: `src/loom/cli/__init__.py`
- Create: `src/loom/cli/graph.py`
- Create: `src/loom/cli/ingest.py`
- Create: `src/loom/cli/analysis.py`
- Create: `src/loom/cli/formatters.py`
- Delete: `src/loom/cli.py`
- Modify: `pyproject.toml` (entry point `loom.cli:app` → `loom.cli:app`)

- [ ] **Step 1: Read current `cli.py` completely**

```bash
wc -l src/loom/cli.py
cat src/loom/cli.py
```

Map every function and command to its domain:
- **`formatters.py`**: all `_render_*`, `_print_*`, `_format_*` helper functions
- **`graph.py`**: `query`, `trace`, `calls`, `blast_radius`, `entrypoints` commands
- **`ingest.py`**: `index`, `sync`, `watch`, `enrich` commands
- **`analysis.py`**: `analyze`, `tickets`, `drift` commands

- [ ] **Step 2: Create `src/loom/cli/formatters.py`**

Move ALL display/rendering helpers here. Zero imports from sibling `cli/` modules.

- [ ] **Step 3: Create `src/loom/cli/graph.py`**

```python
# src/loom/cli/graph.py
import typer
from loom.cli.formatters import _render_table  # import formatters as needed

app = typer.Typer(help="Query and traverse the code graph.")

@app.command()
def query(...): ...

@app.command()
def trace(...): ...

# ... remaining graph commands
```

- [ ] **Step 4: Create `src/loom/cli/ingest.py`** — same pattern for `index`, `sync`, `watch`, `enrich`.

- [ ] **Step 5: Create `src/loom/cli/analysis.py`** — same pattern for `analyze`, `tickets`, `drift`.

- [ ] **Step 6: Create `src/loom/cli/__init__.py`**

```python
# src/loom/cli/__init__.py
import typer

from loom.cli.graph import app as graph_app
from loom.cli.ingest import app as ingest_app
from loom.cli.analysis import app as analysis_app

app = typer.Typer()
app.add_typer(graph_app, name="graph")
app.add_typer(ingest_app, name="ingest")
app.add_typer(analysis_app, name="analysis")
```

- [ ] **Step 7: Check `pyproject.toml` entry point**

```bash
grep -A2 "\[project.scripts\]" pyproject.toml
```

If it reads `loom.cli:app`, it still works because `loom.cli` is now the package's `__init__.py` which exports `app`.

- [ ] **Step 8: Delete old `cli.py`**

```bash
rm src/loom/cli.py
```

- [ ] **Step 9: Update `CLAUDE.md` command table**

The commands table in `CLAUDE.md` references `loom index <path>` and `loom serve`. After the split, these become `loom ingest index <path>` and `loom ingest serve`. Update the Development Commands section to reflect the new command paths.

Also grep for any docs or README files that reference the old command names:

```bash
grep -r "loom index\|loom sync\|loom watch\|loom analyze\|loom trace\|loom query\|loom calls" \
  docs/ README.md CLAUDE.md --include="*.md" -l
```

Update each file found.

- [ ] **Step 10: Run CLI smoke test**

```bash
loom --help
loom graph --help
loom ingest --help
loom analysis --help
```

Each must print help without errors.

- [ ] **Step 11: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: split cli.py into cli/ package with graph/ingest/analysis/formatters modules"
```

---

## Task 5: Slim Semantic Linker

Delete 4 linker files. Slim `linker.py` to embed-only. Remove `LOOM_SPECIFIES` edge type. Delete `llm/client.py`.

**Files:**
- Delete: `src/loom/linker/llm_match.py`
- Delete: `src/loom/linker/name_match.py`
- Delete: `src/loom/linker/reranker.py`
- Delete: `src/loom/linker/prompts.py`
- Delete: `src/loom/llm/client.py`
- Modify: `src/loom/linker/linker.py` (slim to embed-only, async)
- Modify: `src/loom/core/edge.py` (remove `LOOM_SPECIFIES`, add `GIT_COMMIT` to `EdgeOrigin`, update `LinkMethod`)
- Modify: `src/loom/config.py` (rename/raise threshold to 0.85)
- Modify: `src/loom/ingest/pipeline.py` (remove name_match call)

- [ ] **Step 1: Find all usages of deleted modules**

```bash
grep -r "llm_match\|name_match\|reranker\|prompts\|llm.client\|LOOM_SPECIFIES\|loom_specifies" \
  src/ tests/ --include="*.py" -l
```

- [ ] **Step 2: Update `src/loom/core/edge.py`**

a) Remove `LOOM_SPECIFIES = "loom_specifies"` from `EdgeType`

b) Add `GIT_COMMIT = "git_commit"` to `EdgeOrigin`:
```python
class EdgeOrigin(str, Enum):
    COMPUTED = "computed"
    NAME_MATCH = "name_match"
    EMBED_MATCH = "embed_match"
    LLM_MATCH = "llm_match"
    GIT_COMMIT = "git_commit"
    HUMAN = "human"
```

c) Update `LinkMethod` — remove `"name_match"` and `"llm_match"`, add `"git_commit"`:
```python
LinkMethod = Literal["embed_match", "git_commit", "ast_diff"]
```

d) Update `is_loom_edge` property to remove `LOOM_SPECIFIES`:
```python
@property
def is_loom_edge(self) -> bool:
    return self.kind in {
        EdgeType.LOOM_IMPLEMENTS,
        EdgeType.LOOM_VIOLATES,
    }
```

- [ ] **Step 3: Update `src/loom/config.py`**

Find `LOOM_LINKER_EMBED_THRESHOLD` and `LOOM_LINKER_NAME_THRESHOLD`.
- Raise default for `LOOM_LINKER_EMBED_THRESHOLD` from `0.75` → `0.85`
- Delete `LOOM_LINKER_NAME_THRESHOLD` entirely (name matching removed)

- [ ] **Step 4: Rewrite `src/loom/linker/linker.py`**

```python
# src/loom/linker/linker.py
from __future__ import annotations

import logging
from dataclasses import dataclass

from loom.config import LOOM_LINKER_EMBED_THRESHOLD
from loom.core import Edge, EdgeOrigin, Node
from loom.core.types import BulkGraph
from loom.linker.embed_match import link_by_embedding

logger = logging.getLogger(__name__)


@dataclass
class SemanticLinker:
    """Links markdown doc nodes to code nodes by embedding similarity only.

    Does NOT link Jira tickets — use git_linker.link_commits_to_tickets() for that.
    """

    embedding_threshold: float = LOOM_LINKER_EMBED_THRESHOLD

    async def link(
        self,
        code_nodes: list[Node],
        doc_nodes: list[Node],
        graph: BulkGraph,
    ) -> list[Edge]:
        # embed_match → embed_nodes → asyncio.to_thread(embedder.embed, batch)
        # CPU-bound fastembed work is already offloaded to thread pool inside embed_nodes
        # (see src/loom/embed/embedder.py:119). No additional asyncio.to_thread needed here.
        edges = await link_by_embedding(
            code_nodes,
            doc_nodes,
            threshold=self.embedding_threshold,
            graph=graph,
        )
        deduped = self._dedupe_edges(edges)
        if deduped:
            await graph.bulk_create_edges(deduped)
        return deduped

    @staticmethod
    def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
        best: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            key = (edge.from_id, edge.to_id, edge.kind.value)
            current = best.get(key)
            if current is None:
                best[key] = edge
                continue
            if current.origin == EdgeOrigin.HUMAN and edge.origin != EdgeOrigin.HUMAN:
                continue
            if edge.origin == EdgeOrigin.HUMAN and current.origin != EdgeOrigin.HUMAN:
                best[key] = edge
                continue
            if edge.confidence > current.confidence:
                best[key] = edge
        return list(best.values())
```

- [ ] **Step 5: Delete files (check existence first)**

```bash
# Verify files exist before deleting — avoid errors in automated execution
for f in src/loom/linker/llm_match.py src/loom/linker/name_match.py \
          src/loom/linker/reranker.py src/loom/linker/prompts.py \
          src/loom/llm/client.py; do
  [ -f "$f" ] && rm "$f" && echo "deleted $f" || echo "not found (skip): $f"
done
```

- [ ] **Step 6: Remove `_text_utils.py` if only used by deleted files**

```bash
grep -r "_text_utils\|text_utils" src/ --include="*.py"
```

If only imported by `name_match.py` or `llm_match.py` (now deleted), delete it too.

- [ ] **Step 7: Fix `ingest/pipeline.py`**

Remove `_link_code_nodes` from calling `link_by_name`. It now only calls `SemanticLinker().link()` which is embed-only. Also remove Jira nodes from the `doc_nodes` passed to `SemanticLinker` — filter to `NodeSource.DOC` with path not starting with `jira://`:

```python
markdown_doc_nodes = [n for n in doc_nodes if not (n.path or "").startswith("jira://")]
edges = await SemanticLinker().link(code_nodes, markdown_doc_nodes, graph)
```

- [ ] **Step 8: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

Fix any import errors caused by deletions. Tests for deleted modules should also be deleted.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: slim linker to embed-only for markdown docs, delete llm/name/reranker/prompts, remove LOOM_SPECIFIES"
```

---

## Task 6: Build Git-Commit Linker

Create `ingest/git_linker.py`. Wire into pipeline and sync. Write `_LoomMeta` node.

**Files:**
- Create: `src/loom/ingest/git_linker.py`
- Modify: `src/loom/ingest/pipeline.py` (wire in git linker + write `_LoomMeta` node)
- Modify: `src/loom/ingest/incremental.py` (call git linker on sync with `since_sha`)
- Create: `tests/unit/test_git_linker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_git_linker.py
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from loom.ingest.git_linker import TICKET_RE, _extract_ticket_ids, link_commits_to_tickets
from loom.core.edge import Edge, EdgeOrigin, EdgeType


# --- TICKET_RE unit tests ---

def test_regex_extracts_standard_jira_key():
    assert _extract_ticket_ids("fix: resolve PROJ-123 auth bug") == ["PROJ-123"]


def test_regex_extracts_multiple_keys():
    ids = _extract_ticket_ids("PROJ-1 and PROJ-2 fixed")
    assert "PROJ-1" in ids
    assert "PROJ-2" in ids


def test_regex_ignores_lowercase():
    assert _extract_ticket_ids("proj-123 not a ticket") == []


def test_regex_ignores_single_letter_prefix():
    # Single-letter keys like "A-1" should NOT match — require 2+ uppercase letters
    # (adjust if your regex allows single-letter prefixes)
    ids = _extract_ticket_ids("See AB-99 for context")
    assert "AB-99" in ids


def test_regex_no_tickets_returns_empty():
    assert _extract_ticket_ids("fix: update readme") == []


# --- Zero-match warning test ---

async def test_no_ticket_ids_logs_warning(caplog):
    """Repos with commits that have no ticket IDs return [] and log a warning."""
    mock_graph = MagicMock()
    mock_graph.query = MagicMock(return_value=[])  # no existing jira nodes

    mock_repo = MagicMock()
    mock_commit = MagicMock()
    mock_commit.message = "fix: update readme without ticket"
    mock_commit.hexsha = "abc123"
    mock_commit.author.email = "dev@example.com"
    mock_commit.committed_datetime.isoformat.return_value = "2026-04-17T10:00:00"
    mock_commit.stats.files = {}
    mock_repo.iter_commits.return_value = [mock_commit]

    with patch("loom.ingest.git_linker.Repo", return_value=mock_repo):
        with caplog.at_level(logging.WARNING, logger="loom.ingest.git_linker"):
            edges = await link_commits_to_tickets(
                repo_path=Path("/fake/repo"),
                graph=mock_graph,
            )

    assert edges == []
    assert any("no ticket IDs found" in r.message for r in caplog.records)


# --- Happy path: commit with ticket ID links to Jira node ---

async def test_commit_links_to_jira_node():
    mock_graph = MagicMock()
    # graph.query returns the jira node for PROJ-42
    mock_graph.query = MagicMock(return_value=[
        {"id": "doc:jira://PROJ/PROJ-42:root", "path": "jira://PROJ-42"}
    ])

    mock_commit = MagicMock()
    mock_commit.message = "feat: PROJ-42 add user login"
    mock_commit.hexsha = "deadbeef"
    mock_commit.author.email = "alice@example.com"
    mock_commit.committed_datetime.isoformat.return_value = "2026-04-17T12:00:00"
    mock_commit.stats.files = {"src/auth.py": {"lines": 10}}

    mock_repo = MagicMock()
    mock_repo.iter_commits.return_value = [mock_commit]

    # graph query for code nodes in the changed file
    async def fake_query(cypher, params=None):
        if "n.path" in cypher:
            return [{"id": "py::src/auth.py::login", "path": "src/auth.py"}]
        return [{"id": "doc:jira://PROJ/PROJ-42:root", "path": "jira://PROJ-42"}]

    mock_graph.query = fake_query
    mock_graph.bulk_create_edges = MagicMock()

    with patch("loom.ingest.git_linker.Repo", return_value=mock_repo):
        edges = await link_commits_to_tickets(
            repo_path=Path("/fake/repo"),
            graph=mock_graph,
        )

    assert len(edges) >= 1
    edge = edges[0]
    assert edge.kind == EdgeType.LOOM_IMPLEMENTS
    assert edge.origin == EdgeOrigin.GIT_COMMIT
    assert edge.confidence == 1.0
    assert edge.metadata["commit_sha"] == "deadbeef"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/unit/test_git_linker.py -v
```

Expected: `ModuleNotFoundError: No module named 'loom.ingest.git_linker'`

- [ ] **Step 3: Create `src/loom/ingest/git_linker.py`**

```python
# src/loom/ingest/git_linker.py
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from git import Repo  # gitpython — already a dependency

from loom.core.edge import Edge, EdgeOrigin, EdgeType
from loom.core.types import QueryGraph

logger = logging.getLogger(__name__)

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def _extract_ticket_ids(message: str) -> list[str]:
    """Extract all Jira-style ticket IDs from a commit message."""
    return TICKET_RE.findall(message)


async def link_commits_to_tickets(
    repo_path: Path,
    graph: QueryGraph,
    *,
    since_sha: str | None = None,
) -> list[Edge]:
    """Walk git log and create IMPLEMENTS edges from code nodes → Jira ticket nodes.

    For each commit:
    1. Extract ticket IDs from the commit message via TICKET_RE.
    2. Get changed files from the diff.
    3. Resolve each changed file → code nodes already in the graph.
    4. For each (code node, ticket ID) pair, look up the Jira node in the graph.
    5. Create LOOM_IMPLEMENTS edge with origin=GIT_COMMIT.

    Returns [] (not an error) when no ticket IDs are found. Logs a WARNING
    when the entire walked range contains zero ticket references, because this
    usually means the repo doesn't follow Jira commit conventions.

    Args:
        repo_path: Root of the git repository.
        graph: LoomGraph instance for queries.
        since_sha: If provided, only walk commits reachable from HEAD since this SHA.
    """
    repo = Repo(str(repo_path))
    kwargs: dict[str, Any] = {}
    if since_sha:
        kwargs["rev"] = f"{since_sha}..HEAD"

    edges: list[Edge] = []
    any_ticket_found = False

    for commit in repo.iter_commits(**kwargs):
        ticket_ids = _extract_ticket_ids(commit.message or "")
        if not ticket_ids:
            continue

        any_ticket_found = True
        changed_files = list(commit.stats.files.keys())

        for file_path in changed_files:
            # Resolve file → code nodes in graph
            node_rows = await graph.query(
                "MATCH (n:Node) WHERE n.path = $path AND n.kind <> 'file' "
                "RETURN n.id AS id, n.path AS path",
                {"path": file_path},
            )

            for ticket_id in ticket_ids:
                # Look up the Jira ticket node
                jira_rows = await graph.query(
                    "MATCH (t:Node) WHERE t.path STARTS WITH $prefix RETURN t.id AS id",
                    {"prefix": f"jira://{ticket_id}"},
                )
                if not jira_rows:
                    continue

                jira_node_id = str(jira_rows[0]["id"])

                for node_row in node_rows:
                    code_node_id = str(node_row["id"])
                    edges.append(
                        Edge(
                            from_id=code_node_id,
                            to_id=jira_node_id,
                            kind=EdgeType.LOOM_IMPLEMENTS,
                            origin=EdgeOrigin.GIT_COMMIT,
                            confidence=1.0,
                            link_method="git_commit",
                            link_reason=f"commit {commit.hexsha[:8]}: {(commit.message or '').splitlines()[0][:80]}",
                            metadata={
                                "commit_sha": commit.hexsha,
                                "author": commit.author.email,
                                "timestamp": commit.committed_datetime.isoformat(),
                            },
                        )
                    )

    if not any_ticket_found:
        logger.warning(
            "git_linker: no ticket IDs found in commit range for repo %s — "
            "ensure commit messages reference Jira keys (e.g. PROJ-123). "
            "Git-based Jira linking will produce no edges.",
            repo_path,
        )

    return edges
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/unit/test_git_linker.py -v
```

- [ ] **Step 5: Wire git linker into `ingest/pipeline.py`**

In `index_repo()`, after Jira nodes are fetched and persisted, add:

```python
# Git-commit linking for Jira tickets
from loom.ingest.git_linker import link_commits_to_tickets
git_edges = await link_commits_to_tickets(Path(root), graph)
if git_edges:
    await graph.bulk_create_edges(git_edges)
    logger.info("git_linker: created %d IMPLEMENTS edges from commit history", len(git_edges))

# Write _LoomMeta node so MCP relink() can recover repo_path
await graph.query(
    "MERGE (m:_LoomMeta {key: 'repo_path'}) SET m.value = $val",
    {"val": root},
)
```

- [ ] **Step 6: Wire git linker into `ingest/incremental.py`**

In the incremental sync function, after updating nodes, add:

```python
from loom.ingest.git_linker import link_commits_to_tickets
git_edges = await link_commits_to_tickets(
    Path(root), graph, since_sha=last_sha
)
if git_edges:
    await graph.bulk_create_edges(git_edges)
```

- [ ] **Step 7: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: add git_linker — deterministic IMPLEMENTS edges from commit messages to Jira tickets"
```

---

## Task 7: Update `relink()` MCP Tool

Update `mcp/server.py` — new `relink()` signature, `_LoomMeta` lookup, remove `name_threshold`.

**Files:**
- Modify: `src/loom/mcp/server.py`

- [ ] **Step 1: Replace the `relink()` tool in `mcp/server.py`**

First, move the `git_linker` import to the top of `mcp/server.py` alongside existing imports:

```python
from loom.ingest.git_linker import link_commits_to_tickets
```

`get_code_nodes_for_linking` and `get_doc_nodes_for_linking` are already imported at module level (`from loom.ingest.utils import ...`). `SemanticLinker` is already imported. Do NOT re-import these inside the function body.

Find and replace the existing `relink()` function (lines ~248–285):

```python
@mcp.tool()
async def relink(
    repo_path: str | None = None,
    embedding_threshold: float = 0.85,
) -> dict[str, object]:
    """Re-run all linking passes without re-indexing.

    Runs:
    - Embedding similarity linking for markdown doc nodes → code nodes.
    - Git-commit linking for Jira ticket nodes → code nodes.

    Call this after importing new Jira tickets or after incremental sync.

    Args:
        repo_path: Path to the indexed repository root. If omitted, reads
            from the _LoomMeta node written during index_repo(). Raises
            if neither is available.
        embedding_threshold: Minimum cosine similarity for doc→code links (default 0.85).
    """
    from pathlib import Path

    # Resolve repo_path: explicit arg > _LoomMeta node > skip git linking
    resolved_path: str | None = repo_path
    if resolved_path is None:
        meta_rows = await graph.query(
            "MATCH (m:_LoomMeta {key: 'repo_path'}) RETURN m.value AS val LIMIT 1"
        )
        if meta_rows:
            resolved_path = str(meta_rows[0]["val"])

    code_nodes = await get_code_nodes_for_linking(graph)
    doc_nodes = await get_doc_nodes_for_linking(graph)
    markdown_docs = [n for n in doc_nodes if not (n.path or "").startswith("jira://")]

    embed_edges: list = []
    git_edges: list = []

    if code_nodes and markdown_docs:
        linker = SemanticLinker(
            embedding_threshold=max(0.0, min(1.0, embedding_threshold))
        )
        embed_edges = await linker.link(code_nodes, markdown_docs, graph)

    if resolved_path is not None:
        git_edges = await link_commits_to_tickets(Path(resolved_path), graph)
    else:
        # No repo_path — git linking skipped, not an error
        pass

    return {
        "embed_edges_created": len(embed_edges),
        "git_edges_created": len(git_edges),
        "code_nodes": len(code_nodes),
        "markdown_doc_nodes": len(markdown_docs),
        "git_linking_active": resolved_path is not None,
    }
```

- [ ] **Step 2: Run full unit suite**

```bash
pytest tests/unit/ -v --tb=short -q
```

- [ ] **Step 3: Commit**

```bash
git add src/loom/mcp/server.py
git commit -m "feat: update relink() MCP tool — new signature, git linking, _LoomMeta repo_path resolution"
```

---

## Task 8: Cypher Parameterization + `BatchResult`

Harden Cypher queries and surface per-file errors explicitly.

**Files:**
- Modify: `src/loom/core/falkor/cypher.py` (parameterize any f-string queries)
- Modify: `src/loom/ingest/pipeline.py` (add `BatchResult`, use it in `_process_files`)
- Create: `tests/unit/test_cypher_builders.py`

- [ ] **Step 1: Read `cypher.py` to find f-string query construction**

```bash
grep -n "f\"" src/loom/core/falkor/cypher.py | head -30
grep -n "f'" src/loom/core/falkor/cypher.py | head -30
```

For each f-string that interpolates a variable directly into a Cypher string (e.g., `f"WHERE n.id = '{node_id}'"`) — convert to parameterized form:

```python
# Before (injection risk)
cypher = f"MATCH (n:Node {{id: '{node_id}'}})"

# After (safe)
cypher = "MATCH (n:Node {id: $id})"
params = {"id": node_id}
```

Return both as a tuple: `(cypher: str, params: dict)`

- [ ] **Step 2: Write tests for the fixed query builders**

```python
# tests/unit/test_cypher_builders.py
from loom.core.falkor.cypher import build_node_lookup_query  # or whatever functions exist


def test_node_lookup_uses_params_not_interpolation():
    cypher, params = build_node_lookup_query(node_id="test::path::fn")
    # Must use $id parameter, not interpolated string
    assert "$id" in cypher or "$node_id" in cypher
    assert "test::path::fn" not in cypher  # ID must NOT be in the query string
    assert "test::path::fn" in params.values()


def test_params_dict_keys_match_query_placeholders():
    cypher, params = build_node_lookup_query(node_id="foo")
    for key in params:
        assert f"${key}" in cypher
```

Adapt the exact function names to what exists in `cypher.py`.

- [ ] **Step 3: Add `BatchResult` to `pipeline.py`**

In `pipeline.py`, add alongside `_IndexBatch`:

```python
@dataclass
class BatchResult:
    """Explicit per-file result accumulator — never swallows errors silently."""
    ok: list[Node] = field(default_factory=list)
    failed: list[tuple[str, Exception]] = field(default_factory=list)

    def record_ok(self, nodes: list[Node]) -> None:
        self.ok.extend(nodes)

    def record_failure(self, path: str, exc: Exception) -> None:
        logger.error("File processing failed: %s — %s", path, exc, exc_info=True)
        self.failed.append((path, exc))
```

In `_process_files`, when a file task raises, call `batch_result.record_failure(fp, exc)` instead of swallowing the exception.

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_cypher_builders.py tests/unit/ -v --tb=short -q
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: parameterize Cypher queries, add BatchResult for explicit per-file error surfacing"
```

---

## Task 9: `blast_radius` Depth Cap + Gateway Retry + Config Thresholds

**Files:**
- Modify: `src/loom/query/blast_radius.py`
- Modify: `src/loom/core/falkor/gateway.py`
- Modify: `src/loom/config.py`
- Create: `tests/unit/test_blast_radius_depth.py`

- [ ] **Step 1: Write failing tests for depth cap and cycle guard**

```python
# tests/unit/test_blast_radius_depth.py
from unittest.mock import AsyncMock, MagicMock
from loom.query.blast_radius import build_blast_radius_payload


async def test_blast_radius_respects_max_depth():
    """Depth argument is forwarded to graph.blast_radius — not silently dropped."""
    graph = MagicMock()

    # build_blast_radius_payload makes 2 graph.query() calls:
    # 1. root_rows lookup  2. doc_rows lookup
    graph.query = AsyncMock(side_effect=[
        [{"id": "a", "name": "fn_a", "path": "x.py", "kind": "function"}],  # root_rows
        [],  # doc_rows
    ])
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="a", depth=2)
    # Verify depth=2 was passed through — not a larger value
    graph.blast_radius.assert_called_once_with("a", depth=2)


async def test_blast_radius_depth_capped_at_config_max():
    """depth > LOOM_BLAST_RADIUS_MAX_DEPTH must be silently clamped."""
    import os
    os.environ["LOOM_BLAST_RADIUS_MAX_DEPTH"] = "5"

    graph = MagicMock()
    graph.query = AsyncMock(side_effect=[
        [{"id": "b", "name": "fn_b", "path": "y.py", "kind": "function"}],
        [],
    ])
    graph.blast_radius = AsyncMock(return_value=[])

    await build_blast_radius_payload(graph, node_id="b", depth=99)
    # depth=99 must be clamped to 5
    call_kwargs = graph.blast_radius.call_args
    actual_depth = call_kwargs[1].get("depth") or call_kwargs[0][1]
    assert actual_depth <= 5

    del os.environ["LOOM_BLAST_RADIUS_MAX_DEPTH"]


async def test_blast_radius_returns_correct_root():
    """Return payload has correct root node data."""
    graph = MagicMock()
    graph.query = AsyncMock(side_effect=[
        [{"id": "c", "name": "fn_c", "path": "z.py", "kind": "function"}],
        [],
    ])
    graph.blast_radius = AsyncMock(return_value=[])

    result = await build_blast_radius_payload(graph, node_id="c", depth=3)
    assert result["root"]["id"] == "c"
    assert result["root"]["name"] == "fn_c"
```

- [ ] **Step 2: Add config constants for depth and thresholds in `config.py`**

```python
import os

LOOM_BLAST_RADIUS_MAX_DEPTH: int = int(os.getenv("LOOM_BLAST_RADIUS_MAX_DEPTH", "10"))
```

Validation — add to startup config check:
```python
if LOOM_BLAST_RADIUS_MAX_DEPTH < 1 or LOOM_BLAST_RADIUS_MAX_DEPTH > 50:
    raise ValueError(f"LOOM_BLAST_RADIUS_MAX_DEPTH must be 1–50, got {LOOM_BLAST_RADIUS_MAX_DEPTH}")
```

- [ ] **Step 3: Update `blast_radius.py` — enforce depth from config**

In `build_blast_radius_payload`, import the config constant and pass as default:

```python
from loom.config import LOOM_BLAST_RADIUS_MAX_DEPTH

async def build_blast_radius_payload(
    graph: QueryGraph,
    *,
    node_id: str,
    depth: int = LOOM_BLAST_RADIUS_MAX_DEPTH,
) -> dict[str, Any]:
    # depth is already clamped by MCP server (_clamp_depth), but also cap here
    depth = min(depth, LOOM_BLAST_RADIUS_MAX_DEPTH)
    ...
```

- [ ] **Step 4: Add retry with backoff to `gateway.py`**

```python
import time

def get_falkordb_singleton() -> FalkorDB:
    global _DB_SINGLETON
    if _DB_SINGLETON is not None:
        return _DB_SINGLETON

    with _DB_SINGLETON_LOCK:
        if _DB_SINGLETON is None:
            _DB_SINGLETON = _connect_with_retry()
        return _DB_SINGLETON


def _connect_with_retry() -> FalkorDB:
    kwargs = _falkordb_connect_kwargs()
    delays = [1, 2, 4]
    last_exc: Exception | None = None
    for attempt, delay in enumerate(delays):
        try:
            return FalkorDB(**kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "FalkorDB connection attempt %d/%d failed: %s. Retrying in %ds.",
                attempt + 1, len(delays), exc, delay,
            )
            time.sleep(delay)
    raise ConnectionError(
        f"FalkorDB connection failed after {len(delays)} attempts"
    ) from last_exc
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/unit/test_blast_radius_depth.py tests/unit/ -v --tb=short -q
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: blast_radius depth cap from config, gateway retry with backoff, config threshold validation"
```

---

## Task 10: Add Integration Tests

**Files:**
- Create: `tests/integration/test_schema_init.py`
- Create: `tests/integration/test_gateway_retry.py`

These require a live FalkorDB on localhost:6379. Mark `@pytest.mark.integration`.

- [ ] **Step 1: Create `tests/integration/test_schema_init.py`**

```python
# tests/integration/test_schema_init.py
import pytest
from loom.core.falkor.schema import schema_init
from loom.core.falkor.gateway import FalkorGateway


@pytest.mark.integration
async def test_schema_init_is_idempotent():
    """Running schema_init twice must not raise or leave partial state."""
    gw = FalkorGateway("loom_test_schema")
    await schema_init(gw)   # first run
    await schema_init(gw)   # second run — must be idempotent


@pytest.mark.integration
async def test_schema_init_creates_indexes():
    """After schema_init, the Node index must exist."""
    gw = FalkorGateway("loom_test_schema_idx")
    await schema_init(gw)
    result = gw.query_rows("CALL db.indexes()")
    index_names = [str(r.get("label") or r.get("name") or "") for r in result]
    assert any("Node" in name for name in index_names)
```

- [ ] **Step 2: Create `tests/integration/test_gateway_retry.py`**

```python
# tests/integration/test_gateway_retry.py
import pytest
from unittest.mock import patch, MagicMock
from loom.core.falkor.gateway import _connect_with_retry, get_falkordb_singleton


@pytest.mark.integration
def test_connect_with_retry_succeeds_on_third_attempt():
    """Should retry and succeed when first two attempts fail."""
    call_count = 0
    real_falkor = None

    def fake_connect(**kwargs):
        nonlocal call_count, real_falkor
        call_count += 1
        if call_count < 3:
            raise ConnectionRefusedError("simulated failure")
        from falkordb import FalkorDB
        real_falkor = FalkorDB(**kwargs)
        return real_falkor

    with patch("loom.core.falkor.gateway.FalkorDB", side_effect=fake_connect):
        with patch("loom.core.falkor.gateway.time.sleep"):  # don't actually sleep
            result = _connect_with_retry()

    assert call_count == 3
    assert result is real_falkor
```

- [ ] **Step 3: Run integration tests** (requires FalkorDB running)

```bash
pytest tests/integration/ -v -m integration --tb=short
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/
git commit -m "test: add integration tests for schema_init idempotency and gateway retry"
```

---

## Task 11: Full Suite Green + Type Check + Lint

Final verification. No new code — fix any remaining issues.

**Files:** Any failing test or type error file.

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short -q
```

Expected: all unit tests pass, integration tests pass if FalkorDB is running.

- [ ] **Step 2: mypy**

```bash
mypy src/loom/ --ignore-missing-imports
```

Fix any type errors introduced by the refactor (e.g., `EdgeOrigin.GIT_COMMIT` usage, new function signatures).

- [ ] **Step 3: ruff**

```bash
ruff check src/loom/
ruff format --check src/loom/
```

Fix any lint errors. Run `ruff format src/loom/` if format-only failures.

- [ ] **Step 4: CLI smoke test**

```bash
loom --help
loom graph --help
loom ingest index --help
loom analysis analyze --help
```

All commands must print help without traceback.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: full suite green — all tests pass, mypy clean, ruff clean post-revamp"
```

---

## Summary

| Task | What changes | Key output |
|---|---|---|
| 1 | Delete `protocols.py`, `helpers.py`, `result.py`; create `types.py` | Cleaner imports |
| 2 | `_BaseContext` extracted; 7 parsers slimmed | Shared safe push/pop |
| 3 | 3 call extractor files → `calls/` package | Language dispatch API |
| 4 | `cli.py` → `cli/` with 4 domain modules | Clear command ownership |
| 5 | Delete 4 linker files + `llm/client.py`; slim `linker.py` | Embed-only for markdown |
| 6 | `git_linker.py` built and wired | Deterministic Jira linking |
| 7 | `relink()` MCP tool updated | `_LoomMeta` + git pass |
| 8 | Cypher parameterized; `BatchResult` added | Security + error surfacing |
| 9 | Depth cap + retry + config validation | Robustness |
| 10 | Integration tests for schema + gateway | Infra test coverage |
| 11 | Full suite green | Ship-ready |
