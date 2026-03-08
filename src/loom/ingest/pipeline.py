from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from inspect import isawaitable
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Protocol

from loom.analysis.code.parser import parse_code
from loom.analysis.code.extractor import extract_summaries
from loom.core import Edge, LoomGraph, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.embed.embedder import embed_nodes
from loom.ingest.code.walker import walk_repo
from loom.ingest.errors import append_index_error
from loom.ingest.result import IndexError, IndexResult
from loom.ingest.utils import get_doc_nodes_for_linking, invalidate_edges_for_file, merge_nodes_by_id
from loom.ingest.code.registry import get_registry
from loom.linker.linker import SemanticLinker

from loom.ingest.integrations.jira import JiraConfig, fetch_jira_nodes


def _merge_file_result(batch: _IndexBatch, file_result: _FileProcessResult) -> None:
    batch.files_skipped += file_result.files_skipped
    batch.files_updated += file_result.files_updated
    batch.files_added += file_result.files_added
    batch.nodes_to_upsert.extend(file_result.nodes_to_upsert)
    batch.edges_to_upsert.extend(file_result.edges_to_upsert)
    batch.errors.extend(file_result.errors)


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...

    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


_GET_FILE_NODES = "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"
_DELETE_NODE_BY_ID = "MATCH (n {id: $id}) DETACH DELETE n"
_DELETE_NODES_BY_PATH = "MATCH (n {path: $path}) DETACH DELETE n"
_DELETE_NODES_BY_PATH_PREFIX = "MATCH (n) WHERE n.path STARTS WITH $path_prefix DETACH DELETE n"
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


@dataclass
class _FileProcessResult:
    files_skipped: int = 0
    files_updated: int = 0
    files_added: int = 0
    nodes_to_upsert: list[Node] = field(default_factory=list)
    edges_to_upsert: list[Edge] = field(default_factory=list)
    errors: list[IndexError] = field(default_factory=list)


CallTracer = Callable[[str, list[Node]], list[Edge]]


def _file_node_id(path: str) -> str:
    return f"{NodeKind.FILE.value}:{path}"


def _path_from_file_node_id(file_id: str) -> str | None:
    prefix = f"{NodeKind.FILE.value}:"
    if not file_id.startswith(prefix):
        return None
    path = file_id[len(prefix):]
    return path or None


def _compute_file_hash(path: str) -> str:
    return content_hash_bytes(Path(path).read_bytes())


async def _load_stored_file_hashes(graph: _Graph) -> dict[str, str]:
    rows = await graph.query(_GET_FILE_NODES)
    out: dict[str, str] = {}
    for row in rows:
        node_id = row.get("id")
        ch = row.get("content_hash")
        if isinstance(node_id, str) and isinstance(ch, str) and ch:
            out[node_id] = ch
    return out


def _make_file_node(path: str, *, content_hash: str) -> Node:
    p = Path(path)
    return Node(
        id=_file_node_id(path),
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path,
        content_hash=content_hash,
        metadata={},
    )


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
    return sorted(set(all_files))


def _get_call_tracer(path: str) -> tuple[CallTracer | None, str | None]:
    handler = get_registry().get_handler_for_path(path)
    if handler is None:
        return None, None
    return handler.call_tracer, handler.call_tracer_error_message


def _append_docs_batch(docs_path: str, batch: _IndexBatch) -> None:
    try:
        from loom.ingest.docs.base import walk_docs

        doc_nodes, doc_edges = walk_docs(docs_path)
        batch.nodes_to_upsert.extend(doc_nodes)
        batch.edges_to_upsert.extend(doc_edges)
    except Exception as e:
        append_index_error(batch.errors, path=str(docs_path), phase="parse", error=e)


async def _append_jira_batch(jira: JiraConfig, batch: _IndexBatch) -> None:
    try:
        jira_nodes_result = fetch_jira_nodes(jira)
        jira_nodes = await jira_nodes_result if isawaitable(jira_nodes_result) else jira_nodes_result
        batch.nodes_to_upsert.extend(jira_nodes)
    except Exception as e:
        append_index_error(batch.errors, path=jira.project_key, phase="jira", error=e)


async def _process_file(
    graph: _Graph,
    *,
    fp: str,
    stored_hash: str | None,
    exclude_tests: bool,
    batch: _FileProcessResult,
) -> _FileProcessResult:
    try:
        file_hash = _compute_file_hash(fp)
    except Exception as e:
        append_index_error(batch.errors, path=fp, phase="hash", error=e)
        return batch

    if stored_hash is not None and stored_hash == file_hash:
        batch.files_skipped += 1
        return batch

    is_new_file = stored_hash is None

    # Parse code first - don't commit any state changes until this succeeds
    try:
        nodes = await asyncio.to_thread(parse_code, fp, exclude_tests=exclude_tests)
    except Exception as e:
        append_index_error(batch.errors, path=fp, phase="parse", error=e)
        return batch

    # Parse succeeded - now we can safely update counters and invalidate edges
    if is_new_file:
        batch.files_added += 1
    else:
        batch.files_updated += 1
        try:
            await invalidate_edges_for_file(graph, path=fp)
        except Exception as e:
            append_index_error(batch.errors, path=fp, phase="invalidate", error=e)
            return batch

    # Add file node with new hash and parsed code nodes
    batch.nodes_to_upsert.append(_make_file_node(fp, content_hash=file_hash))
    batch.nodes_to_upsert.extend(nodes)

    # Trace calls (failure here is non-fatal - we still have valid parsed nodes)
    tracer, _ = _get_call_tracer(fp)
    if tracer is None:
        return batch

    try:
        edges = await asyncio.to_thread(tracer, fp, nodes)
        batch.edges_to_upsert.extend(edges)
    except Exception as e:
        append_index_error(batch.errors, path=fp, phase="calls", error=e)

    return batch


async def _delete_missing_files(
    graph: _Graph,
    deleted_file_ids: set[str],
    errors: list[IndexError],
) -> None:
    for file_id in sorted(deleted_file_ids):
        try:
            path = _path_from_file_node_id(file_id)
            if path is not None:
                await graph.query(_DELETE_NODES_BY_PATH, {"path": path})
            else:
                await graph.query(_DELETE_NODE_BY_ID, {"id": file_id})
        except Exception as e:
            append_index_error(errors, path=str(path), phase="persist", error=e)


async def _delete_existing_repo_nodes(
    graph: _Graph,
    *,
    root: str,
    errors: list[IndexError],
) -> None:
    try:
        await graph.query(_DELETE_NODES_BY_PATH_PREFIX, {"path_prefix": root})
    except Exception as e:
        append_index_error(errors, path=root, phase="persist", error=e)


async def _persist_batch(graph: _Graph, root: str, batch: _IndexBatch) -> None:
    if batch.nodes_to_upsert:
        try:
            await graph.bulk_create_nodes(batch.nodes_to_upsert)
        except Exception as e:
            append_index_error(batch.errors, path=root, phase="persist", error=e)

    if batch.edges_to_upsert:
        try:
            await graph.bulk_create_edges(batch.edges_to_upsert)
        except Exception as e:
            append_index_error(batch.errors, path=root, phase="persist", error=e)


async def _query_graph_counts(graph: _Graph, root: str, errors: list[IndexError]) -> tuple[int, int]:
    node_count = 0
    edge_count = 0
    try:
        rows = await graph.query(_COUNT_NODES)
        node_count = int(rows[0]["c"]) if rows else 0
        rows = await graph.query(_COUNT_EDGES)
        edge_count = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        append_index_error(errors, path=root, phase="summarize", error=e)
    return node_count, edge_count


async def index_repo(
    path: str,
    graph: LoomGraph | _Graph,
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

    stored_hash_by_file_id = {} if force else await _load_stored_file_hashes(graph)
    current_files = _collect_repo_files(root)

    current_file_ids = {_file_node_id(fp) for fp in current_files}
    stored_file_ids = set(stored_hash_by_file_id.keys())

    if docs_path is not None:
        _append_docs_batch(docs_path, batch)
    if jira is not None:
        await _append_jira_batch(jira, batch)

    semaphore = asyncio.Semaphore(_DEFAULT_INGEST_CONCURRENCY)

    async def _process_file_bounded(fp: str) -> _FileProcessResult:
        file_id = _file_node_id(fp)
        stored_hash = stored_hash_by_file_id.get(file_id)
        async with semaphore:
            return await _process_file(
                graph,
                fp=fp,
                stored_hash=stored_hash,
                exclude_tests=exclude_tests,
                batch=_FileProcessResult(),
            )

    async def _process_file_tagged(fp: str) -> tuple[str, _FileProcessResult | None, Exception | None]:
        try:
            return fp, await _process_file_bounded(fp), None
        except Exception as e:
            return fp, None, e

    file_tasks = [asyncio.create_task(_process_file_tagged(fp)) for fp in current_files]
    try:
        for completed_task in asyncio.as_completed(file_tasks):
            fp, file_result, task_error = await completed_task
            if task_error is not None:
                append_index_error(batch.errors, path=fp, phase="process", error=task_error)
                continue
            if file_result is None:
                continue
            _merge_file_result(batch, file_result)
    finally:
        for task in file_tasks:
            if not task.done():
                task.cancel()
        for task in file_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # Handle deleted files (present in graph, missing on disk)
    deleted_file_ids = stored_file_ids - current_file_ids
    files_deleted = len(deleted_file_ids)

    if deleted_file_ids:
        await _delete_missing_files(graph, deleted_file_ids, batch.errors)

    # Extract static summaries for all nodes (no LLM calls)
    try:
        batch.nodes_to_upsert = await extract_summaries(batch.nodes_to_upsert)
    except Exception as e:
        append_index_error(batch.errors, path=root, phase="summarize", error=e)
        await _persist_batch(graph, root, batch)
        # Don't continue with embedding/linking if summarization failed
        node_count, edge_count = await _query_graph_counts(graph, root, batch.errors)
        duration_ms = (perf_counter() - t0) * 1000.0
        return IndexResult(
            node_count=node_count,
            edge_count=edge_count,
            file_count=len(current_files),
            files_skipped=batch.files_skipped,
            files_updated=batch.files_updated,
            files_added=batch.files_added,
            files_deleted=files_deleted,
            error_count=len(batch.errors),
            duration_ms=duration_ms,
            errors=batch.errors,
        )

    # Compute embeddings for nodes with summaries before persisting nodes,
    # so we avoid a second full node upsert pass when embedding succeeds.
    nodes_with_summaries = [n for n in batch.nodes_to_upsert if n.summary]
    if nodes_with_summaries:
        try:
            embedded_nodes = await embed_nodes(nodes_with_summaries)
            embedded_by_id = {node.id: node for node in embedded_nodes}
            batch.nodes_to_upsert = [embedded_by_id.get(node.id, node) for node in batch.nodes_to_upsert]
        except Exception as e:
            append_index_error(batch.errors, path=root, phase="embed", error=e)
            # Continue without embeddings - nodes are still valid

    await _persist_batch(graph, root, batch)

    code_nodes = _collect_code_nodes_for_linking(batch)
    if code_nodes:
        doc_nodes = merge_nodes_by_id(
            _collect_doc_nodes_for_linking(batch),
            await get_doc_nodes_for_linking(graph),
        )
        if doc_nodes:
            try:
                await SemanticLinker().link(code_nodes, doc_nodes, graph)
            except Exception as e:
                link_path = str(docs_path) if docs_path is not None else (jira.project_key if jira is not None else root)
                append_index_error(batch.errors, path=link_path, phase="link", error=e)

    node_count, edge_count = await _query_graph_counts(graph, root, batch.errors)

    duration_ms = (perf_counter() - t0) * 1000.0

    return IndexResult(
        node_count=node_count,
        edge_count=edge_count,
        file_count=len(current_files),
        files_skipped=batch.files_skipped,
        files_updated=batch.files_updated,
        files_added=batch.files_added,
        files_deleted=files_deleted,
        error_count=len(batch.errors),
        duration_ms=duration_ms,
        errors=batch.errors,
    )
