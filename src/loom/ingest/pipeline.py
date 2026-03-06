from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from time import perf_counter

from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.ingest.code.walker import walk_repo
from loom.linker.linker import SemanticLinker

from loom.ingest.result import IndexError, IndexResult


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...

    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


_GET_FILE_NODES = "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"

_DELETE_NON_HUMAN_EDGES_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin IS NULL OR r.origin <> 'human'
DELETE r
"""

_MARK_HUMAN_EDGES_STALE_FOR_FILE = """
MATCH (a {path: $path})-[r]->()
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = 'source_changed'
"""

_DELETE_NODE_BY_ID = "MATCH (n {id: $id}) DETACH DELETE n"
_COUNT_NODES = "MATCH (n) RETURN count(n) AS c"
_COUNT_EDGES = "MATCH ()-[r]->() RETURN count(r) AS c"


@dataclass
class _IndexBatch:
    files_skipped: int = 0
    files_updated: int = 0
    files_added: int = 0
    nodes_to_upsert: list[Node] | None = None
    edges_to_upsert: list[Edge] | None = None
    errors: list[IndexError] | None = None

    def __post_init__(self) -> None:
        if self.nodes_to_upsert is None:
            self.nodes_to_upsert = []
        if self.edges_to_upsert is None:
            self.edges_to_upsert = []
        if self.errors is None:
            self.errors = []


CallTracer = Callable[[str, list[Node]], list[Edge]]


def _file_node_id(path: str) -> str:
    return f"{NodeKind.FILE.value}:{path}"


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


async def _invalidate_edges_for_file(graph: _Graph, *, path: str) -> None:
    await graph.query(_DELETE_NON_HUMAN_EDGES_FOR_FILE, {"path": path})
    await graph.query(_MARK_HUMAN_EDGES_STALE_FOR_FILE, {"path": path})


def _get_call_tracer(path: str) -> tuple[CallTracer | None, str | None]:
    lower = path.lower()
    if lower.endswith(".py"):
        from loom.analysis.code.calls import trace_calls_for_file

        return trace_calls_for_file, "python call tracing failed"
    if lower.endswith((".ts", ".tsx")):
        from loom.analysis.code.calls_ts import trace_calls_for_ts_file

        return trace_calls_for_ts_file, "typescript call tracing failed"
    if lower.endswith(".java"):
        from loom.analysis.code.calls_java import trace_calls_for_java_file

        return trace_calls_for_java_file, "java call tracing failed"
    return None, None


def _append_docs_batch(docs_path: str, batch: _IndexBatch) -> None:
    try:
        from loom.ingest.docs.base import walk_docs

        doc_nodes, doc_edges = walk_docs(docs_path)
        batch.nodes_to_upsert.extend(doc_nodes)
        batch.edges_to_upsert.extend(doc_edges)
    except Exception as e:
        batch.errors.append(IndexError(path=str(docs_path), phase="parse", message=str(e)))


async def _process_file(
    graph: _Graph,
    *,
    fp: str,
    stored_hash: str | None,
    exclude_tests: bool,
    batch: _IndexBatch,
) -> None:
    file_hash = _compute_file_hash(fp)
    if stored_hash is not None and stored_hash == file_hash:
        batch.files_skipped += 1
        return

    if stored_hash is None:
        batch.files_added += 1
    else:
        batch.files_updated += 1
        await _invalidate_edges_for_file(graph, path=fp)

    batch.nodes_to_upsert.append(_make_file_node(fp, content_hash=file_hash))

    try:
        nodes = parse_code(fp, exclude_tests=exclude_tests)
        batch.nodes_to_upsert.extend(nodes)
    except Exception as e:
        batch.errors.append(IndexError(path=fp, phase="parse", message=str(e)))
        return

    tracer, error_message = _get_call_tracer(fp)
    if tracer is None or error_message is None:
        return

    try:
        batch.edges_to_upsert.extend(tracer(fp, nodes))
    except Exception:
        batch.errors.append(IndexError(path=fp, phase="calls", message=error_message))


async def _delete_missing_files(graph: _Graph, deleted_file_ids: set[str], errors: list[IndexError]) -> None:
    for file_id in sorted(deleted_file_ids):
        try:
            await graph.query(_DELETE_NODE_BY_ID, {"id": file_id})
        except Exception as e:
            errors.append(IndexError(path=file_id, phase="persist", message=str(e)))


async def _persist_batch(graph: _Graph, root: str, batch: _IndexBatch) -> None:
    if batch.nodes_to_upsert:
        try:
            await graph.bulk_create_nodes(batch.nodes_to_upsert)
        except Exception as e:
            batch.errors.append(IndexError(path=root, phase="persist", message=str(e)))

    if batch.edges_to_upsert:
        try:
            await graph.bulk_create_edges(batch.edges_to_upsert)
        except Exception as e:
            batch.errors.append(IndexError(path=root, phase="persist", message=str(e)))


async def _query_graph_counts(graph: _Graph, root: str, errors: list[IndexError]) -> tuple[int, int]:
    node_count = 0
    edge_count = 0
    try:
        rows = await graph.query(_COUNT_NODES)
        node_count = int(rows[0]["c"]) if rows else 0
        rows = await graph.query(_COUNT_EDGES)
        edge_count = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        errors.append(IndexError(path=root, phase="summarize", message=str(e)))
    return node_count, edge_count


async def index_repo(
    path: str,
    graph: LoomGraph | _Graph,
    *,
    force: bool = False,
    exclude_tests: bool = False,
    docs_path: str | None = None,
) -> IndexResult:
    """Index a repo into the graph.

    - `force=True`: re-parse and upsert everything.
    - `force=False`: skip files whose stored FILE node `content_hash` matches.

    This function is intentionally conservative: it doesn't attempt NodeDiffer yet.
    It only performs file-level skip/update decisions.
    """

    t0 = perf_counter()
    root = str(Path(path).resolve())

    stored_hash_by_file_id = {} if force else await _load_stored_file_hashes(graph)
    current_files = _collect_repo_files(root)

    current_file_ids = {_file_node_id(fp) for fp in current_files}
    stored_file_ids = set(stored_hash_by_file_id.keys())

    batch = _IndexBatch()

    if docs_path is not None:
        _append_docs_batch(docs_path, batch)

    for fp in current_files:
        file_id = _file_node_id(fp)
        stored_hash = stored_hash_by_file_id.get(file_id)
        await _process_file(
            graph,
            fp=fp,
            stored_hash=stored_hash,
            exclude_tests=exclude_tests,
            batch=batch,
        )

    # Handle deleted files (present in graph, missing on disk)
    deleted_file_ids = stored_file_ids - current_file_ids
    files_deleted = len(deleted_file_ids)

    if deleted_file_ids:
        await _delete_missing_files(graph, deleted_file_ids, batch.errors)

    await _persist_batch(graph, root, batch)

    if docs_path is not None:
        code_nodes = _collect_code_nodes_for_linking(batch)
        doc_nodes = _collect_doc_nodes_for_linking(batch)
        if code_nodes and doc_nodes:
            try:
                await SemanticLinker().link(code_nodes, doc_nodes, graph)
            except Exception as e:
                batch.errors.append(IndexError(path=str(docs_path), phase="link", message=str(e)))

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
