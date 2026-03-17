from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from tqdm import tqdm

from loom.analysis.code.extractor import extract_summaries
from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.core.protocols import BulkGraph
from loom.embed.embedder import embed_nodes
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo
from loom.ingest.helpers import build_contains_edges, file_node_id, make_file_node
from loom.ingest.integrations.jira import JiraConfig, fetch_jira_nodes
from loom.ingest.result import IndexError, IndexResult
from loom.ingest.utils import (
    delete_nodes_by_ids,
    get_doc_nodes_for_linking,
    get_node_ids_by_path,
    invalidate_edges_for_file,
    merge_nodes_by_id,
)
from loom.linker.linker import SemanticLinker

logger = logging.getLogger(__name__)


def _merge_file_result(batch: _IndexBatch, file_result: _IndexBatch) -> None:
    batch.files_skipped += file_result.files_skipped
    batch.files_updated += file_result.files_updated
    batch.files_added += file_result.files_added
    batch.nodes_to_upsert.extend(file_result.nodes_to_upsert)
    batch.edges_to_upsert.extend(file_result.edges_to_upsert)
    batch.errors.extend(file_result.errors)


_GET_FILE_NODES = "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"
_DELETE_NODE_BY_ID = "MATCH (n {id: $id}) DETACH DELETE n"
_DELETE_NODES_BY_PATH = "MATCH (n {path: $path}) DETACH DELETE n"
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
    errors: list[IndexError] = field(default_factory=list)


_FileProcessResult = _IndexBatch


CallTracer = Callable[[str, list[Node]], list[Edge]]


def _file_node_id(path: str) -> str:
    return file_node_id(path)


def _path_from_file_node_id(file_id: str) -> str | None:
    prefix = f"{NodeKind.FILE.value}:"
    return file_id[len(prefix) :] if file_id.startswith(prefix) else None


def _compute_file_hash(path: str) -> str:
    return content_hash_bytes(Path(path).read_bytes())


async def _load_stored_file_hashes(graph: BulkGraph) -> dict[str, str]:
    rows = await graph.query(_GET_FILE_NODES)
    out: dict[str, str] = {}
    for row in rows:
        node_id = row.get("id")
        ch = row.get("content_hash")
        if isinstance(node_id, str) and isinstance(ch, str) and ch:
            out[node_id] = ch
    return out


def _collect_code_nodes_for_linking(batch: _IndexBatch) -> list[Node]:
    return [
        node
        for node in batch.nodes_to_upsert
        if node.source == NodeSource.CODE and node.kind != NodeKind.FILE
    ]


def _collect_doc_nodes_for_linking(batch: _IndexBatch) -> list[Node]:
    return [node for node in batch.nodes_to_upsert if node.source == NodeSource.DOC]


def _collect_repo_files(root: str) -> list[str]:
    files_by_lang = walk_repo(root)
    all_files: list[str] = []
    for files in files_by_lang.values():
        all_files.extend(files)
    return sorted(all_files)


def _get_call_tracer(path: str) -> tuple[CallTracer | None, str | None]:
    handler = get_registry().get_handler_for_path(path)
    if handler is None:
        return None, None
    return handler.call_tracer, handler.call_tracer_error_message


def _build_global_symbol_map(nodes: list[Node]) -> dict[str, list[Node]]:
    """Build a cross-file name→[Node] map for all function/method nodes."""
    from loom.core import NodeKind

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
    new_node_ids = {_file_node_id(fp), *(node.id for node in nodes)}
    if not is_new_file:
        stale_ids = sorted(old_ids - new_node_ids)
        if stale_ids:
            await delete_nodes_by_ids(graph, stale_ids)

    # Add file node with new hash and parsed code nodes
    batch.nodes_to_upsert.append(make_file_node(fp, content_hash=file_hash))
    batch.nodes_to_upsert.extend(nodes)
    batch.edges_to_upsert.extend(build_contains_edges(nodes))

    # Trace calls (failure here is non-fatal - we still have valid parsed nodes)
    tracer, _ = _get_call_tracer(fp)
    if tracer is None:
        return batch

    edges = await asyncio.to_thread(tracer, fp, nodes)
    batch.edges_to_upsert.extend(edges)

    return batch


async def _delete_missing_files(
    graph: BulkGraph,
    deleted_file_ids: set[str],
    errors: list[IndexError],
) -> None:
    for file_id in sorted(deleted_file_ids):
        path = _path_from_file_node_id(file_id)
        if path is not None:
            await graph.query(_DELETE_NODES_BY_PATH, {"path": path})
        else:
            await graph.query(_DELETE_NODE_BY_ID, {"id": file_id})


async def _delete_existing_repo_nodes(
    graph: BulkGraph,
    *,
    root: str,
    errors: list[IndexError],
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
    graph: BulkGraph, root: str, errors: list[IndexError]
) -> tuple[int, int]:
    rows = await graph.query(_COUNT_NODES)
    node_count = int(rows[0]["c"]) if rows else 0
    rows = await graph.query(_COUNT_EDGES)
    edge_count = int(rows[0]["c"]) if rows else 0
    return node_count, edge_count


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

    print(f"Linking {len(code_nodes)} code nodes with {len(doc_nodes)} doc nodes...")
    link_t0 = perf_counter()
    await SemanticLinker().link(code_nodes, doc_nodes, graph)
    print(f"Completed linking in {(perf_counter() - link_t0):.2f}s")


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
        file_id = _file_node_id(fp)
        stored_hash = stored_hash_by_file_id.get(file_id)
        processed_count += 1
        logger.info(f"Processing file {processed_count}/{total_files}: {fp}")
        async with semaphore:
            return await _process_file(
                graph,
                fp=fp,
                stored_hash=stored_hash,
                exclude_tests=exclude_tests,
                batch=_FileProcessResult(),
            )

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


async def _append_optional_jira(
    *, jira: JiraConfig | None, root: str, batch: _IndexBatch
) -> None:
    if jira is None:
        return
    jira_t0 = perf_counter()
    await _append_jira_batch(jira, batch)
    logger.info(
        "index_repo append_jira root=%s project=%s total_nodes=%d duration_ms=%.2f",
        root,
        jira.project_key,
        len(batch.nodes_to_upsert),
        (perf_counter() - jira_t0) * 1000.0,
    )


async def _delete_missing_file_nodes(
    *,
    graph: BulkGraph,
    root: str,
    current_files: list[str],
    stored_hash_by_file_id: dict[str, str],
    batch: _IndexBatch,
) -> int:
    current_file_ids = {_file_node_id(fp) for fp in current_files}
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
    path: str,
    graph: BulkGraph,
    *,
    force: bool = False,
    exclude_tests: bool = False,
    docs_path: str | None = None,
    jira: JiraConfig | None = None,
) -> IndexResult:
    """Index a repo into the graph.

    - `force=True`: re-parse and upsert everything.
    - `force=False`: skip files whose stored FILE node `content_hash` matches.

    This function is intentionally conservative: it doesn't attempt NodeDiffer yet.
    It only performs file-level skip/update decisions.
    """
    t0 = perf_counter()
    root = str(Path(path).resolve())
    batch = _IndexBatch()

    if force:
        await _delete_existing_repo_nodes(graph, root=root, errors=batch.errors)

    stored_hash_by_file_id = await _load_hashes(force=force, graph=graph, root=root)
    current_files = _collect_files(root=root)

    _append_optional_docs(docs_path=docs_path, root=root, batch=batch)
    await _append_optional_jira(jira=jira, root=root, batch=batch)

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
    )
