from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from time import perf_counter

from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeType, LoomGraph, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.ingest.code.walker import walk_repo

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


def _collect_repo_files(root: str) -> list[str]:
    files_by_lang = walk_repo(root)
    all_files: list[str] = []
    for files in files_by_lang.values():
        all_files.extend(files)
    return sorted(set(all_files))


async def _invalidate_edges_for_file(graph: _Graph, *, path: str) -> None:
    # Delete all non-human edges from nodes in the file; they'll be recomputed.
    await graph.query(_DELETE_NON_HUMAN_EDGES_FOR_FILE, {"path": path})
    # Human edges are preserved but flagged stale.
    await graph.query(_MARK_HUMAN_EDGES_STALE_FOR_FILE, {"path": path})


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

    files_skipped = 0
    files_updated = 0
    files_added = 0

    errors: list[IndexError] = []

    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    if docs_path is not None:
        try:
            from loom.ingest.docs.base import walk_docs

            doc_nodes, doc_edges = walk_docs(docs_path)
            nodes_to_upsert.extend(doc_nodes)
            edges_to_upsert.extend(doc_edges)
        except Exception as e:
            errors.append(IndexError(path=str(docs_path), phase="parse", message=str(e)))

    for fp in current_files:
        file_id = _file_node_id(fp)
        file_hash = _compute_file_hash(fp)

        stored_hash = stored_hash_by_file_id.get(file_id)
        if stored_hash is not None and stored_hash == file_hash:
            files_skipped += 1
            continue

        if stored_hash is None:
            files_added += 1
        else:
            files_updated += 1
            await _invalidate_edges_for_file(graph, path=fp)

        # Ensure FILE node exists/updates.
        nodes_to_upsert.append(_make_file_node(fp, content_hash=file_hash))

        # Parse symbols for supported languages.
        try:
            nodes = parse_code(fp, exclude_tests=exclude_tests)
            nodes_to_upsert.extend(nodes)
        except Exception as e:
            errors.append(IndexError(path=fp, phase="parse", message=str(e)))
            continue

        # Minimal structural edges: only CALLS edges for Python for now.
        if fp.lower().endswith(".py"):
            try:
                from loom.analysis.code.calls import trace_calls_for_file

                edges_to_upsert.extend(trace_calls_for_file(fp, nodes))
            except Exception:
                errors.append(
                    IndexError(path=fp, phase="calls", message="python call tracing failed")
                )

        if fp.lower().endswith((".ts", ".tsx")):
            try:
                from loom.analysis.code.calls_ts import trace_calls_for_ts_file

                edges_to_upsert.extend(trace_calls_for_ts_file(fp, nodes))
            except Exception:
                errors.append(
                    IndexError(path=fp, phase="calls", message="typescript call tracing failed")
                )

        if fp.lower().endswith(".java"):
            try:
                from loom.analysis.code.calls_java import trace_calls_for_java_file

                edges_to_upsert.extend(trace_calls_for_java_file(fp, nodes))
            except Exception:
                errors.append(IndexError(path=fp, phase="calls", message="java call tracing failed"))

    # Handle deleted files (present in graph, missing on disk)
    deleted_file_ids = stored_file_ids - current_file_ids
    files_deleted = len(deleted_file_ids)

    if deleted_file_ids:
        for file_id in sorted(deleted_file_ids):
            try:
                await graph.query("MATCH (n {id: $id}) DETACH DELETE n", {"id": file_id})
            except Exception as e:
                errors.append(IndexError(path=file_id, phase="persist", message=str(e)))

    if nodes_to_upsert:
        try:
            await graph.bulk_create_nodes(nodes_to_upsert)
        except Exception as e:
            errors.append(IndexError(path=root, phase="persist", message=str(e)))

    if edges_to_upsert:
        try:
            await graph.bulk_create_edges(edges_to_upsert)
        except Exception as e:
            errors.append(IndexError(path=root, phase="persist", message=str(e)))

    node_count = 0
    edge_count = 0
    try:
        rows = await graph.query("MATCH (n) RETURN count(n) AS c")
        node_count = int(rows[0]["c"]) if rows else 0
        rows = await graph.query("MATCH ()-[r]->() RETURN count(r) AS c")
        edge_count = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        errors.append(IndexError(path=root, phase="summarize", message=str(e)))

    duration_ms = (perf_counter() - t0) * 1000.0

    return IndexResult(
        node_count=node_count,
        edge_count=edge_count,
        file_count=len(current_files),
        files_skipped=files_skipped,
        files_updated=files_updated,
        files_added=files_added,
        files_deleted=files_deleted,
        error_count=len(errors),
        duration_ms=duration_ms,
        errors=errors,
    )
