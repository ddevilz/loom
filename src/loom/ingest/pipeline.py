from __future__ import annotations

<<<<<<< HEAD
import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

from loom.analysis.code.parser import parse_code
from loom.core.edge import Edge, EdgeType
from loom.core.graph import LoomGraph
from loom.core.node import Node, NodeKind, NodeSource
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo
from loom.ingest.utils import sha256_of_file

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
=======
import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Literal

from tqdm import tqdm

from loom.analysis.code.extractor import extract_summaries
from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.core.types import BulkGraph
from loom.embed.embedder import embed_nodes
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo
from loom.ingest.git_linker import link_commits_to_tickets
from loom.ingest.integrations.jira import JiraConfig, fetch_jira_nodes
from loom.ingest.utils import (
    delete_nodes_by_ids,
    delete_nodes_by_path,
    get_doc_nodes_for_linking,
    get_node_ids_by_path,
    invalidate_edges_for_file,
    merge_nodes_by_id,
)
from loom.linker.linker import SemanticLinker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (inlined from loom.ingest.helpers)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Result types (inlined from loom.ingest.result)
# ---------------------------------------------------------------------------

IndexPhase = Literal[
    "parse",
    "calls",
    "calls_global",
    "persist",
    "summarize",
    "link",
    "embed",
    "hash",
    "invalidate",
    "jira",
    "process",
]


@dataclass(frozen=True)
class IngestError:
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
    errors: list[IngestError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def append_index_error(
    errors: list[IngestError],
    *,
    path: str,
    phase: IndexPhase,
    error: Exception,
) -> None:
    logger.error(
        "Indexing error in phase '%s' for '%s': %s", phase, path, error, exc_info=True
    )
    errors.append(IngestError(path=path, phase=phase, message=str(error)))


def _merge_file_result(batch: _IndexBatch, file_result: _IndexBatch) -> None:
    batch.files_skipped += file_result.files_skipped
    batch.files_updated += file_result.files_updated
    batch.files_added += file_result.files_added
    batch.nodes_to_upsert.extend(file_result.nodes_to_upsert)
    batch.edges_to_upsert.extend(file_result.edges_to_upsert)
    batch.errors.extend(file_result.errors)


_GET_FILE_NODES = "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"
_DELETE_NODES_BY_PATH_PREFIX = (
    "MATCH (n) WHERE n.path STARTS WITH $path_prefix DETACH DELETE n"
)
_COUNT_NODES = "MATCH (n) RETURN count(n) AS c"
_COUNT_EDGES = "MATCH ()-[r]->() RETURN count(r) AS c"
_DEFAULT_INGEST_CONCURRENCY = 8


@dataclass
class _IndexBatch:
    files_skipped: int = 0
    files_updated: int = 0
    files_added: int = 0
    nodes_to_upsert: list[Node] = field(default_factory=list)
    edges_to_upsert: list[Edge] = field(default_factory=list)
    errors: list[IngestError] = field(default_factory=list)


_FileProcessResult = _IndexBatch
>>>>>>> main


@dataclass
class IndexResult:
    repo_path: Path
    files_parsed: int
    files_skipped: int
    nodes_written: int
    edges_written: int
    errors: list[str] = field(default_factory=list)


<<<<<<< HEAD
def _remap_id(old_id: str, abs_path: str, rel_path: str) -> str:
    """Remap a node ID from absolute path to POSIX-relative path form."""
    # Symbol-bearing nodes: "kind:{abs_path}:{symbol}"
    if f":{abs_path}:" in old_id:
        return old_id.replace(f":{abs_path}:", f":{rel_path}:", 1)
    # FILE nodes: "file:{abs_path}" (no trailing colon)
    if old_id.endswith(f":{abs_path}"):
        return old_id[: -len(abs_path)] + rel_path
    return old_id
=======
def _path_fromfile_node_id(file_id: str) -> str | None:
    prefix = f"{NodeKind.FILE.value}:"
    return file_id[len(prefix) :] if file_id.startswith(prefix) else None
>>>>>>> main


def _get_call_tracer(abs_path: str):  # type: ignore[return]
    handler = get_registry().get_handler_for_path(abs_path)
    if handler is None:
        return None
    return handler.call_tracer


<<<<<<< HEAD
def _parse_file(file_path: Path, *, repo_root: Path) -> ParseResult:
    """Parse a single file. Returns nodes/edges/errors.
=======
async def _load_stored_file_hashes(graph: BulkGraph) -> dict[str, str]:
    rows = await graph.query(_GET_FILE_NODES)
    out: dict[str, str] = {}
    for row in rows:
        node_id = row.get("id")
        ch = row.get("content_hash")
        if isinstance(node_id, str) and isinstance(ch, str) and ch:
            out[node_id] = ch
    return out
>>>>>>> main

    Every returned Node has:
      - path = POSIX repo-relative (no leading ./)
      - file_hash = sha256_of_file(file_path)
      - id built with the same rel path
      - content_hash = sha256 of symbol's source slice (set by parser)

<<<<<<< HEAD
    Every returned Edge uses from_id/to_id matching those node IDs.
    Paths are never absolute and never use backslashes.
    """
    abs_path = str(file_path)
    try:
        rel_path = file_path.relative_to(repo_root).as_posix()
    except ValueError:
        return ParseResult(errors=[f"path {abs_path!r} outside repo_root {repo_root}"])

    try:
        file_hash = sha256_of_file(file_path)
    except OSError as exc:
        return ParseResult(errors=[f"hash failed {abs_path}: {exc}"])

    try:
        raw_nodes = parse_code(abs_path)
    except Exception as exc:
        return ParseResult(errors=[f"parse failed {abs_path}: {exc}"])

    # Build abs→rel ID mapping
    id_map: dict[str, str] = {}
    for n in raw_nodes:
        new_id = _remap_id(n.id, abs_path, rel_path)
        id_map[n.id] = new_id

    # Add FILE node (parsers may or may not emit one)
    file_node_id = f"file:{rel_path}"
    file_node = Node(
        id=file_node_id,
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=file_path.name,
        path=rel_path,
        file_hash=file_hash,
        metadata={},
    )

    # Remap parsed nodes
    nodes: list[Node] = [file_node]
    for n in raw_nodes:
        if n.kind == NodeKind.FILE:
            continue  # already added our canonical FILE node above
        new_id = id_map[n.id]
        new_parent_id: str | None = None
        if n.parent_id:
            new_parent_id = id_map.get(n.parent_id, _remap_id(n.parent_id, abs_path, rel_path))
        nodes.append(
            n.model_copy(
                update={
                    "id": new_id,
                    "path": rel_path,
                    "file_hash": file_hash,
                    "parent_id": new_parent_id,
                }
            )
        )

    # Per-file call tracing (uses abs path to read source)
    tracer = _get_call_tracer(abs_path)
    raw_edges: list[Edge] = []
    if tracer is not None:
        try:
            raw_edges = tracer(abs_path, raw_nodes)
        except Exception as exc:
            logger.warning("call tracer failed for %s: %s", rel_path, exc)

    # CONTAINS edges: file → every non-file node
    contains_edges = [
        Edge(
            from_id=file_node_id,
            to_id=id_map.get(n.id, _remap_id(n.id, abs_path, rel_path)),
            kind=EdgeType.CONTAINS,
            confidence=1.0,
        )
        for n in raw_nodes
        if n.kind != NodeKind.FILE and n.parent_id is None
=======
def _collect_code_nodes_for_linking(batch: _IndexBatch) -> list[Node]:
    return [
        node
        for node in batch.nodes_to_upsert
        if node.source == NodeSource.CODE and node.kind != NodeKind.FILE
>>>>>>> main
    ]

    # Remap call edges
    edges: list[Edge] = list(contains_edges)
    for e in raw_edges:
        new_from = id_map.get(e.from_id, _remap_id(e.from_id, abs_path, rel_path))
        new_to = id_map.get(e.to_id, e.to_id)  # keep unresolved: IDs as-is
        edges.append(e.model_copy(update={"from_id": new_from, "to_id": new_to}))

    return ParseResult(nodes=nodes, edges=edges)


<<<<<<< HEAD
def resolve_calls(
    nodes: list[Node], edges: list[Edge], repo_root: Path
) -> tuple[list[Node], list[Edge]]:
    """Enhance cross-file CALLS resolution for Python using a global symbol map."""
    from loom.analysis.code.calls.python import (
        _build_symbol_map,
        trace_calls_for_file_with_global_symbols,
    )
    from loom.ingest.code.languages.constants import EXT_PY, EXT_PYW

    global_symbol_map = _build_symbol_map(nodes)
    if not global_symbol_map:
        return nodes, edges

    by_path: dict[str, list[Node]] = {}
    for n in nodes:
        if n.path:
            by_path.setdefault(n.path, []).append(n)
=======
def _collect_repo_files(root: str) -> list[str]:
    files_by_lang = walk_repo(root)
    all_files: list[str] = []
    for files in files_by_lang.values():
        all_files.extend(files)
    return sorted(all_files)
>>>>>>> main

    python_source_ids: set[str] = set()
    global_call_edges: list[Edge] = []

<<<<<<< HEAD
    for rel_path, file_nodes in by_path.items():
        ext = Path(rel_path).suffix.lower()
        if ext not in (EXT_PY, EXT_PYW):
            continue
        abs_path = str(repo_root / rel_path)
        python_source_ids.update(
            n.id for n in file_nodes if n.kind in {NodeKind.FUNCTION, NodeKind.METHOD}
        )
        try:
            file_edges = trace_calls_for_file_with_global_symbols(
                abs_path, file_nodes, global_symbol_map=global_symbol_map
            )
            global_call_edges.extend(file_edges)
        except Exception as exc:
            logger.warning("resolve_calls failed for %s: %s", rel_path, exc)
=======
def _get_call_tracer(path: str) -> tuple[CallTracer | None, str | None]:
    handler = get_registry().get_handler_for_path(path)
    if handler is None:
        return None, None
    return handler.call_tracer, handler.call_tracer_error_message


def _build_global_symbol_map(nodes: list[Node]) -> dict[str, list[Node]]:
    """Build a cross-file name→[Node] map for all function/method nodes."""
    symbol_map: dict[str, list[Node]] = {}
    for n in nodes:
        if n.kind in {NodeKind.FUNCTION, NodeKind.METHOD}:
            symbol_map.setdefault(n.name, []).append(n)
    return symbol_map


def _group_nodes_by_path(nodes: list[Node]) -> dict[str, list[Node]]:
    grouped: dict[str, list[Node]] = {}
    for node in nodes:
        if node.path:
            grouped.setdefault(node.path, []).append(node)
    return grouped


def _is_python_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".py", ".pyw"}


def _python_call_source_ids(nodes: list[Node]) -> set[str]:
    return {
        node.id
        for node in nodes
        if node.kind in {NodeKind.FUNCTION, NodeKind.METHOD}
        and _is_python_path(node.path)
    }


def _append_docs_batch(docs_path: str, batch: _IndexBatch) -> None:
    from loom.ingest.docs.base import walk_docs

    doc_nodes, doc_edges = walk_docs(docs_path)
    batch.nodes_to_upsert.extend(doc_nodes)
    batch.edges_to_upsert.extend(doc_edges)


async def _append_jira_batch(jira: JiraConfig, batch: _IndexBatch) -> None:
    jira_nodes = await fetch_jira_nodes(jira)
    batch.nodes_to_upsert.extend(jira_nodes)


async def _filter_new_jira_nodes(
    graph: BulkGraph, jira_nodes: list[Node]
) -> list[Node]:
    """Return only Jira nodes not yet present in the graph."""
    if not jira_nodes:
        return jira_nodes
    existing_rows = await graph.query(
        "MATCH (n) WHERE n.id STARTS WITH 'doc:jira://' RETURN n.id AS id"
    )
    existing_ids = {
        row.get("id") for row in existing_rows if isinstance(row.get("id"), str)
    }
    return [n for n in jira_nodes if n.id not in existing_ids]


async def _append_optional_jira(
    *, jira: JiraConfig | None, root: str, batch: _IndexBatch, graph: BulkGraph
) -> None:
    if jira is None:
        return
    jira_t0 = perf_counter()
    jira_nodes = await fetch_jira_nodes(jira)
    new_jira_nodes = await _filter_new_jira_nodes(graph, jira_nodes)
    batch.nodes_to_upsert.extend(new_jira_nodes)
    skipped = len(jira_nodes) - len(new_jira_nodes)
    logger.info(
        "index_repo append_jira root=%s project=%s new_nodes=%d skipped_existing=%d total_nodes=%d duration_ms=%.2f",
        root,
        jira.project_key,
        len(new_jira_nodes),
        skipped,
        len(batch.nodes_to_upsert),
        (perf_counter() - jira_t0) * 1000.0,
    )
    if skipped:
        print(
            f"Jira: {len(new_jira_nodes)} new tickets, {skipped} already indexed (skipped)"
        )


async def _process_file(
    graph: BulkGraph,
    *,
    fp: str,
    stored_hash: str | None,
    exclude_tests: bool,
    batch: _FileProcessResult,
) -> _FileProcessResult:
    file_hash = _compute_file_hash(fp)

    if stored_hash is not None and stored_hash == file_hash:
        batch.files_skipped += 1
        return batch

    is_new_file = stored_hash is None

    # Parse code first - don't commit any state changes until this succeeds
    nodes = await asyncio.to_thread(parse_code, fp, exclude_tests=exclude_tests)

    # Parse succeeded - now we can safely update counters and invalidate edges
    if is_new_file:
        batch.files_added += 1
    else:
        batch.files_updated += 1
        old_ids = set(await get_node_ids_by_path(graph, path=fp))
        await invalidate_edges_for_file(graph, path=fp)
    new_node_ids = {file_node_id(fp), *(node.id for node in nodes)}
    if not is_new_file:
        stale_ids = sorted(old_ids - new_node_ids)
        if stale_ids:
            await delete_nodes_by_ids(graph, stale_ids)

    # Add file node with new hash and parsed code nodes
    batch.nodes_to_upsert.append(make_file_node(fp, content_hash=file_hash))
    batch.nodes_to_upsert.extend(nodes)
    batch.edges_to_upsert.extend(build_contains_edges(nodes))

    # Trace calls (failure here is non-fatal - we still have valid parsed nodes)
    tracer, tracer_error_message = _get_call_tracer(fp)
    if tracer is None:
        return batch

    try:
        edges = await asyncio.to_thread(tracer, fp, nodes)
        batch.edges_to_upsert.extend(edges)
    except Exception as exc:
        logger.warning(
            "call tracer failed for %s: %s",
            fp,
            tracer_error_message or exc,
        )

    return batch


async def _delete_missing_files(
    graph: BulkGraph,
    deleted_file_ids: set[str],
    errors: list[IngestError],
) -> None:
    for file_id in sorted(deleted_file_ids):
        path = _path_fromfile_node_id(file_id)
        if path is not None:
            await delete_nodes_by_path(graph, path=path)
        else:
            await delete_nodes_by_ids(graph, [file_id])
>>>>>>> main

    if not global_call_edges:
        return nodes, edges

<<<<<<< HEAD
    filtered = [
        e for e in edges
        if not (e.kind == EdgeType.CALLS and e.from_id in python_source_ids)
    ]
    return nodes, filtered + global_call_edges
=======
async def _delete_existing_repo_nodes(
    graph: BulkGraph,
    *,
    root: str,
    errors: list[IngestError],
) -> None:
    await graph.query(_DELETE_NODES_BY_PATH_PREFIX, {"path_prefix": root})


async def _persist_batch(graph: BulkGraph, root: str, batch: _IndexBatch) -> None:
    if batch.nodes_to_upsert:
        node_t0 = perf_counter()
        print(f"Persisting {len(batch.nodes_to_upsert)} nodes to database...")
        await graph.bulk_create_nodes(batch.nodes_to_upsert)
        logger.info(
            "index_repo persist_nodes root=%s count=%d duration_ms=%.2f",
            root,
            len(batch.nodes_to_upsert),
            (perf_counter() - node_t0) * 1000.0,
        )
        print(f"Completed node persistence in {(perf_counter() - node_t0):.2f}s")

    if batch.edges_to_upsert:
        edge_t0 = perf_counter()
        print(f"Persisting {len(batch.edges_to_upsert)} edges to database...")
        await graph.bulk_create_edges(batch.edges_to_upsert)
        logger.info(
            "index_repo persist_edges root=%s count=%d duration_ms=%.2f",
            root,
            len(batch.edges_to_upsert),
            (perf_counter() - edge_t0) * 1000.0,
        )
        print(f"Completed edge persistence in {(perf_counter() - edge_t0):.2f}s")


async def _query_graph_counts(
    graph: BulkGraph, root: str, errors: list[IngestError]
) -> tuple[int, int]:
    rows = await graph.query(_COUNT_NODES)
    node_count = int(rows[0]["c"]) if rows else 0
    rows = await graph.query(_COUNT_EDGES)
    edge_count = int(rows[0]["c"]) if rows else 0
    return node_count, edge_count
>>>>>>> main


async def _resolve_global_call_edges(
    root: str,
    batch: _IndexBatch,
) -> list[Edge]:
    from loom.analysis.code.calls import (
        _build_symbol_map,
        trace_calls_for_file_with_global_symbols,
    )
    from loom.ingest.code.languages.constants import EXT_PY, EXT_PYW

    global_symbol_map = _build_symbol_map(batch.nodes_to_upsert)
    if not global_symbol_map:
        return []

    global_call_edges: list[Edge] = []
    for fp, file_nodes in _group_nodes_by_path(batch.nodes_to_upsert).items():
        ext = Path(fp).suffix.lower()
        if ext not in (EXT_PY, EXT_PYW):
            continue
        edges = await asyncio.to_thread(
            trace_calls_for_file_with_global_symbols,
            fp,
            file_nodes,
            global_symbol_map=global_symbol_map,
        )
        global_call_edges.extend(edges)
    return global_call_edges


async def _link_code_nodes(
    graph: BulkGraph,
    batch: _IndexBatch,
    *,
    root: str,
    docs_path: str | None,
    jira: JiraConfig | None,
) -> None:
    code_nodes = _collect_code_nodes_for_linking(batch)
    if not code_nodes:
        print("No code nodes to link")
        return

    stored_doc_nodes = await get_doc_nodes_for_linking(graph)

    doc_nodes = merge_nodes_by_id(
        _collect_doc_nodes_for_linking(batch),
        stored_doc_nodes,
    )
    if not doc_nodes:
        print("No doc nodes to link")
        return

    # Only link markdown doc nodes — Jira ticket linking is handled by git_linker
    markdown_doc_nodes = [n for n in doc_nodes if not (n.path or "").startswith("jira://")]
    if not markdown_doc_nodes:
        print("No markdown doc nodes to link")
        return
    print(f"Linking {len(code_nodes)} code nodes with {len(markdown_doc_nodes)} doc nodes...")
    link_t0 = perf_counter()
    edges = await SemanticLinker().link(code_nodes, markdown_doc_nodes, graph)
    print(
        f"Completed linking: {len(edges)} edges created in {(perf_counter() - link_t0):.2f}s"
    )


async def _process_files(
    graph: BulkGraph,
    *,
    current_files: list[str],
    stored_hash_by_file_id: dict[str, str],
    exclude_tests: bool,
    batch: _IndexBatch,
) -> None:
    semaphore = asyncio.Semaphore(_DEFAULT_INGEST_CONCURRENCY)
    processed_count = 0
    total_files = len(current_files)

    async def _process_one(fp: str) -> _FileProcessResult:
        nonlocal processed_count
        file_id = file_node_id(fp)
        stored_hash = stored_hash_by_file_id.get(file_id)
        async with semaphore:
            processed_count += 1
            logger.info("Processing file %d/%d: %s", processed_count, total_files, fp)
            result = _FileProcessResult()
            try:
                return await _process_file(
                    graph,
                    fp=fp,
                    stored_hash=stored_hash,
                    exclude_tests=exclude_tests,
                    batch=result,
                )
            except Exception as exc:
                append_index_error(result.errors, path=fp, phase="process", error=exc)
                return result

    show_progress = os.environ.get("LOOM_PROGRESS", "1") != "0" and os.isatty(1)
    tasks = [asyncio.create_task(_process_one(fp)) for fp in current_files]
    progress = (
        tqdm(
            total=len(tasks), desc="index files", unit="file", disable=not show_progress
        )
        if tasks
        else None
    )
    try:
        for fut in asyncio.as_completed(tasks):
            file_result = await fut
            _merge_file_result(batch, file_result)
            if progress is not None:
                progress.update(1)
    finally:
        if progress is not None:
            progress.close()


async def _apply_global_call_edges(root: str, batch: _IndexBatch) -> None:
    global_calls_t0 = perf_counter()
    global_call_edges = await _resolve_global_call_edges(root, batch)
    logger.info(
        "index_repo resolve_global_calls root=%s added_edges=%d duration_ms=%.2f",
        root,
        len(global_call_edges),
        (perf_counter() - global_calls_t0) * 1000.0,
    )
    if global_call_edges:
        python_call_source_ids = _python_call_source_ids(batch.nodes_to_upsert)
        batch.edges_to_upsert = [
            e
            for e in batch.edges_to_upsert
            if not (e.kind == EdgeType.CALLS and e.from_id in python_call_source_ids)
        ]
        batch.edges_to_upsert.extend(global_call_edges)


async def _load_hashes(*, force: bool, graph: BulkGraph, root: str) -> dict[str, str]:
    load_hashes_t0 = perf_counter()
    stored_hash_by_file_id = {} if force else await _load_stored_file_hashes(graph)
    logger.info(
        "index_repo load_stored_hashes root=%s count=%d duration_ms=%.2f",
        root,
        len(stored_hash_by_file_id),
        (perf_counter() - load_hashes_t0) * 1000.0,
    )
    return stored_hash_by_file_id


def _collect_files(*, root: str) -> list[str]:
    collect_files_t0 = perf_counter()
    current_files = _collect_repo_files(root)
    logger.info(
        "index_repo collect_repo_files root=%s count=%d duration_ms=%.2f",
        root,
        len(current_files),
        (perf_counter() - collect_files_t0) * 1000.0,
    )
    print(
        f"Found {len(current_files)} files to process in {(perf_counter() - collect_files_t0) * 1000.0:.2f}ms"
    )
    return current_files


def _append_optional_docs(
    *, docs_path: str | None, root: str, batch: _IndexBatch
) -> None:
    if docs_path is None:
        return
    docs_t0 = perf_counter()
    _append_docs_batch(docs_path, batch)
    logger.info(
        "index_repo append_docs root=%s docs_path=%s nodes=%d edges=%d duration_ms=%.2f",
        root,
        docs_path,
        len(batch.nodes_to_upsert),
        len(batch.edges_to_upsert),
        (perf_counter() - docs_t0) * 1000.0,
    )


async def _delete_missing_file_nodes(
    *,
    graph: BulkGraph,
    root: str,
    current_files: list[str],
    stored_hash_by_file_id: dict[str, str],
    batch: _IndexBatch,
) -> int:
    current_file_ids = {file_node_id(fp) for fp in current_files}
    stored_file_ids = set(stored_hash_by_file_id.keys())
    deleted_file_ids = stored_file_ids - current_file_ids
    files_deleted = len(deleted_file_ids)
    if deleted_file_ids:
        delete_missing_t0 = perf_counter()
        await _delete_missing_files(graph, deleted_file_ids, batch.errors)
        logger.info(
            "index_repo delete_missing_files root=%s count=%d duration_ms=%.2f",
            root,
            len(deleted_file_ids),
            (perf_counter() - delete_missing_t0) * 1000.0,
        )
    return files_deleted


async def _summarize_nodes(*, root: str, batch: _IndexBatch) -> None:
    summarize_t0 = perf_counter()
    print(f"Extracting summaries for {len(batch.nodes_to_upsert)} nodes...")
    batch.nodes_to_upsert = await extract_summaries(batch.nodes_to_upsert)
    logger.info(
        "index_repo extract_summaries root=%s nodes=%d duration_ms=%.2f",
        root,
        len(batch.nodes_to_upsert),
        (perf_counter() - summarize_t0) * 1000.0,
    )
    print(f"Completed summary extraction in {(perf_counter() - summarize_t0):.2f}s")


async def _embed_nodes_if_needed(*, root: str, batch: _IndexBatch) -> None:
    nodes_with_summaries = [n for n in batch.nodes_to_upsert if n.summary]
    if not nodes_with_summaries:
        print("No nodes with summaries to embed")
        return
    embed_t0 = perf_counter()
    print(f"Embedding {len(nodes_with_summaries)} nodes with summaries...")
    embedded_nodes = await embed_nodes(nodes_with_summaries)
    embedded_by_id = {node.id: node for node in embedded_nodes}
    batch.nodes_to_upsert = [
        embedded_by_id.get(node.id, node) for node in batch.nodes_to_upsert
    ]
    logger.info(
        "index_repo embed_nodes root=%s nodes=%d duration_ms=%.2f",
        root,
        len(nodes_with_summaries),
        (perf_counter() - embed_t0) * 1000.0,
    )
    print(f"Completed embedding in {(perf_counter() - embed_t0):.2f}s")


async def _count_graph(*, graph: BulkGraph, root: str) -> tuple[int, int]:
    count_t0 = perf_counter()
    node_count, edge_count = await _query_graph_counts(graph, root, errors=[])
    logger.info(
        "index_repo query_graph_counts root=%s node_count=%d edge_count=%d duration_ms=%.2f",
        root,
        node_count,
        edge_count,
        (perf_counter() - count_t0) * 1000.0,
    )
    return node_count, edge_count


def _build_index_result(
    *,
    node_count: int,
    edge_count: int,
    file_count: int,
    files_deleted: int,
    duration_ms: float,
    batch: _IndexBatch,
) -> IndexResult:
    return IndexResult(
        node_count=node_count,
        edge_count=edge_count,
        file_count=file_count,
        files_skipped=batch.files_skipped,
        files_updated=batch.files_updated,
        files_added=batch.files_added,
        files_deleted=files_deleted,
        error_count=len(batch.errors),
        duration_ms=duration_ms,
        errors=batch.errors,
    )


async def index_repo(
<<<<<<< HEAD
    repo_path: Path,
    graph: LoomGraph,
=======
    path: str,
    graph: BulkGraph,
>>>>>>> main
    *,
    workers: int | None = None,
) -> IndexResult:
    """Index a repo into the graph.

    Walk, parse (parallel), cross-file call resolution, per-file atomic replace,
    then community detection and dead-code marking.
    """
<<<<<<< HEAD
    repo_path = repo_path.resolve()

    files_by_lang = walk_repo(str(repo_path))
    all_files: list[Path] = [
        Path(fp) for fps in files_by_lang.values() for fp in fps
    ]

    existing = await graph.get_content_hashes()
    changed: list[Path] = []
    skipped = 0
    for f in all_files:
        rel = f.relative_to(repo_path).as_posix()
        if sha256_of_file(f) == existing.get(rel):
            skipped += 1
        else:
            changed.append(f)

    logger.info(
        "index_repo root=%s total=%d changed=%d skipped=%d",
        repo_path,
        len(all_files),
        len(changed),
        skipped,
    )

    nodes_all: list[Node] = []
    edges_all: list[Edge] = []
    errors: list[str] = []

    max_workers = workers or min(cpu_count(), 8)

    if len(changed) >= 8:
        # Parallel parse via ProcessPoolExecutor
        import functools

        parse_fn = functools.partial(_parse_file, repo_root=repo_path)
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(parse_fn, changed, chunksize=20):
                nodes_all.extend(result.nodes)
                edges_all.extend(result.edges)
                errors.extend(result.errors)
    else:
        for f in changed:
            r = _parse_file(f, repo_root=repo_path)
            nodes_all.extend(r.nodes)
            edges_all.extend(r.edges)
            errors.extend(r.errors)

    # Cross-file call resolution (Python only)
    nodes_all, edges_all = resolve_calls(nodes_all, edges_all, repo_path)

    # Group per-file and atomically replace
    by_path: dict[str, tuple[list[Node], list[Edge]]] = {}
    for n in nodes_all:
        if n.path not in by_path:
            by_path[n.path] = ([], [])
        by_path[n.path][0].append(n)

    for e in edges_all:
        # Assign edge to the path of its source node
        src_path = ""
        if e.from_id.count(":") >= 2:
            src_path = e.from_id.split(":", 2)[1]
        elif e.from_id.startswith("file:"):
            src_path = e.from_id[5:]
        if src_path in by_path:
            by_path[src_path][1].append(e)

    for path, (fn, fe) in by_path.items():
        await graph.replace_file(path, fn, fe)

    # Post-processing analysis
    try:
        from loom.analysis.communities import (
            compute_communities,  # type: ignore[import]
        )

        await compute_communities(graph)
    except ImportError:
        logger.debug("compute_communities not available yet")
    except Exception as exc:
        logger.warning("compute_communities failed: %s", exc)

    try:
        from loom.analysis.coupling import compute_coupling  # type: ignore[import]

        await compute_coupling(graph, repo_path)
    except ImportError:
        logger.debug("compute_coupling not available yet")
    except Exception as exc:
        logger.warning("compute_coupling failed: %s", exc)

    try:
        from loom.analysis.dead_code import mark_dead_code  # type: ignore[import]

        await mark_dead_code(graph)
    except ImportError:
        logger.debug("mark_dead_code not available yet")
    except Exception as exc:
        logger.warning("mark_dead_code failed: %s", exc)

    return IndexResult(
        repo_path=repo_path,
        files_parsed=len(changed),
        files_skipped=skipped,
        nodes_written=len(nodes_all),
        edges_written=len(edges_all),
        errors=errors,
=======
    t0 = perf_counter()
    root = str(Path(path).resolve())
    batch = _IndexBatch()

    if force:
        await _delete_existing_repo_nodes(graph, root=root, errors=batch.errors)

    stored_hash_by_file_id = await _load_hashes(force=force, graph=graph, root=root)
    current_files = _collect_files(root=root)

    _append_optional_docs(docs_path=docs_path, root=root, batch=batch)
    await _append_optional_jira(jira=jira, root=root, batch=batch, graph=graph)

    process_files_t0 = perf_counter()
    await _process_files(
        graph,
        current_files=current_files,
        stored_hash_by_file_id=stored_hash_by_file_id,
        exclude_tests=exclude_tests,
        batch=batch,
    )
    logger.info(
        "index_repo process_files root=%s files=%d files_added=%d files_updated=%d files_skipped=%d nodes=%d edges=%d duration_ms=%.2f",
        root,
        len(current_files),
        batch.files_added,
        batch.files_updated,
        batch.files_skipped,
        len(batch.nodes_to_upsert),
        len(batch.edges_to_upsert),
        (perf_counter() - process_files_t0) * 1000.0,
    )
    print(
        f"Completed processing {len(current_files)} files in {(perf_counter() - process_files_t0):.2f}s"
    )
    print(
        f"Files added: {batch.files_added}, updated: {batch.files_updated}, skipped: {batch.files_skipped}"
    )
    print(f"Nodes: {len(batch.nodes_to_upsert)}, Edges: {len(batch.edges_to_upsert)}")

    files_deleted = await _delete_missing_file_nodes(
        graph=graph,
        root=root,
        current_files=current_files,
        stored_hash_by_file_id=stored_hash_by_file_id,
        batch=batch,
    )

    await _apply_global_call_edges(root, batch)

    await _summarize_nodes(root=root, batch=batch)
    await _embed_nodes_if_needed(root=root, batch=batch)

    await _persist_batch(graph, root, batch)

    link_t0 = perf_counter()
    await _link_code_nodes(
        graph,
        batch,
        root=root,
        docs_path=docs_path,
        jira=jira,
    )
    logger.info(
        "index_repo link_code_nodes root=%s duration_ms=%.2f",
        root,
        (perf_counter() - link_t0) * 1000.0,
    )

    # Git-commit linking for Jira tickets
    git_edges = await link_commits_to_tickets(Path(root), graph)
    if git_edges:
        await graph.bulk_create_edges(git_edges)
        logger.info(
            "index_repo git_linker root=%s edges=%d",
            root,
            len(git_edges),
        )

    # Write _LoomMeta node so MCP relink() can recover repo_path
    await graph.query(
        "MERGE (m:_LoomMeta {key: 'repo_path'}) SET m.value = $val",
        {"val": root},
    )

    node_count, edge_count = await _count_graph(graph=graph, root=root)

    duration_ms = (perf_counter() - t0) * 1000.0
    logger.info(
        "index_repo complete root=%s file_count=%d nodes=%d edges=%d errors=%d duration_ms=%.2f",
        root,
        len(current_files),
        len(batch.nodes_to_upsert),
        len(batch.edges_to_upsert),
        len(batch.errors),
        duration_ms,
    )

    return _build_index_result(
        node_count=node_count,
        edge_count=edge_count,
        file_count=len(current_files),
        files_deleted=files_deleted,
        duration_ms=duration_ms,
        batch=batch,
>>>>>>> main
    )
