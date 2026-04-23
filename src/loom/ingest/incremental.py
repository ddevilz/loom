from __future__ import annotations

<<<<<<< HEAD
import logging
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path

from loom.core.graph import LoomGraph
from loom.ingest.code.walker import walk_repo
from loom.ingest.pipeline import _parse_file, resolve_calls
from loom.ingest.utils import sha256_of_file

logger = logging.getLogger(__name__)

# Allowlist for git ref characters to prevent shell injection
_SAFE_REF = set("0123456789abcdefABCDEF~^/._-HEAD")


def _validate_ref(ref: str) -> None:
    """Raise ValueError if ref contains characters outside the safe allowlist."""
    if not ref or any(c not in _SAFE_REF for c in ref):
        raise ValueError(f"unsafe git ref: {ref!r}")


@dataclass
class SyncResult:
    files_changed: int
    nodes_written: int
    edges_written: int


def _git_diff_files(repo: Path, old: str, new: str) -> list[Path]:
    """Return absolute paths of files changed between two git refs."""
    _validate_ref(old)
    _validate_ref(new)
    out = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", old, new],
        text=True,
=======
import asyncio
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

from loom.analysis.code.extractor import extract_summaries
from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.core.falkor.edge_type_adapter import LOOM_IMPLEMENTS_REL, EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_edge_props, deserialize_node_props
from loom.core.types import BulkGraph
from loom.drift.detector import detect_ast_drift
from loom.embed.embedder import embed_nodes
from loom.ingest.code.registry import get_registry
from loom.ingest.differ import diff_nodes
from loom.ingest.git import get_changed_files
from loom.ingest.pipeline import (
    IndexResult,
    IngestError,
    append_index_error,
    build_contains_edges,
    make_file_node,
)
from loom.ingest.utils import (
    delete_nodes_by_ids,
    get_doc_nodes_for_linking,
    invalidate_edges_for_file,
    mark_human_edges_stale_for_node,
    node_has_human_edges,
)
from loom.linker.linker import SemanticLinker

logger = logging.getLogger(__name__)


def _normalized_changed_path(repo_path: str, relative_path: str) -> str:
    return (Path(repo_path) / relative_path).resolve().as_posix()


def _trace_calls_for_path(path: str, nodes: list[Node]) -> list[Edge]:
    handler = get_registry().get_handler_for_path(path)
    if handler is None or handler.call_tracer is None:
        return []
    return handler.call_tracer(path, nodes)


def _build_file_batch(path: str, nodes: list[Node]) -> tuple[list[Node], list[Edge]]:
    file_hash = content_hash_bytes(Path(path).read_bytes())
    file_node = make_file_node(path, content_hash=file_hash)
    call_edges = _trace_calls_for_path(path, nodes)
    contains_edges = build_contains_edges(nodes)
    return [file_node, *nodes], [*contains_edges, *call_edges]


async def _get_outgoing_human_edges(
    graph: BulkGraph, *, path: str
) -> list[dict[str, Any]]:
    return await graph.query(
        """
        MATCH (a {path: $path})-[r]->(b)
        WHERE r.origin = 'human'
        RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, properties(r) AS props
        """,
        {"path": path},
    )


async def _get_incoming_human_edges(
    graph: BulkGraph, *, path: str
) -> list[dict[str, Any]]:
    return await graph.query(
        """
        MATCH (a)-[r]->(b {path: $path})
        WHERE r.origin = 'human'
        RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, properties(r) AS props
        """,
        {"path": path},
>>>>>>> main
    )
    return [repo / line.strip() for line in out.splitlines() if line.strip()]


<<<<<<< HEAD
async def sync_paths(
    graph: LoomGraph,
    repo_path: Path,
    *,
    old_sha: str | None = None,
    new_sha: str | None = None,
) -> SyncResult:
    """Sync changed files into the graph.

    When old_sha and new_sha are provided, uses git diff to narrow the candidate
    set. Otherwise, walks the whole repo and filters by SHA-256 hash.
    """
    repo_path = repo_path.resolve()

    if old_sha and new_sha:
        raw = _git_diff_files(repo_path, old_sha, new_sha)
        candidates: list[Path] = [c for c in raw if c.exists()]
    else:
        files_by_lang = walk_repo(str(repo_path))
        candidates = [Path(fp) for fps in files_by_lang.values() for fp in fps]

    changed: list[Path] = []
    for f in candidates:
        rel = f.relative_to(repo_path).as_posix()
        stored = await graph.get_file_hash(rel)
        if sha256_of_file(f) != stored:
            changed.append(f)

    if not changed:
        return SyncResult(0, 0, 0)

    import functools

    parse_fn = functools.partial(_parse_file, repo_root=repo_path)
    if len(changed) >= 8:
        with ProcessPoolExecutor(max_workers=min(cpu_count(), 8)) as pool:
            parsed = list(pool.map(parse_fn, changed, chunksize=20))
    else:
        parsed = [parse_fn(f) for f in changed]

    all_nodes = [n for r in parsed for n in r.nodes]
    all_edges = [e for r in parsed for e in r.edges]
    all_nodes, all_edges = resolve_calls(all_nodes, all_edges, repo_path)

    by_path: dict[str, tuple[list, list]] = {}
    for n in all_nodes:
        if n.path not in by_path:
            by_path[n.path] = ([], [])
        by_path[n.path][0].append(n)

    for e in all_edges:
        if e.from_id.startswith("file:"):
            src_path = e.from_id[5:]
        elif e.from_id.count(":") >= 2:
            src_path = e.from_id.split(":", 2)[1]
        else:
            src_path = ""
        if src_path in by_path:
            by_path[src_path][1].append(e)

    for path, (fn, fe) in by_path.items():
        await graph.replace_file(path, fn, fe)

    logger.info(
        "sync_paths repo=%s changed=%d nodes=%d edges=%d",
        repo_path,
        len(changed),
        len(all_nodes),
        len(all_edges),
    )

    return SyncResult(
        files_changed=len(changed),
        nodes_written=len(all_nodes),
        edges_written=len(all_edges),
=======
async def _create_edge(
    graph: BulkGraph,
    *,
    from_id: str,
    to_id: str,
    rel_type: str,
    props: dict[str, Any],
) -> None:
    # Relationship type can't be parameterized in Cypher — validate against known
    # EdgeType names to prevent injection if graph data is tampered with.
    if not EdgeTypeAdapter.is_valid_storage_name(rel_type):
        raise ValueError(f"Unknown edge type {rel_type!r} — refusing to interpolate into Cypher")
    await graph.query(
        f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) MERGE (a)-[r:`{rel_type}`]->(b) SET r += $props",
        {"from_id": from_id, "to_id": to_id, "props": props},
    )


async def _handle_deleted_path(
    graph: BulkGraph,
    *,
    path: str,
    errors: list[IngestError],
) -> None:
    await invalidate_edges_for_file(graph, path=path)
    rows = await graph.query(
        "MATCH (n {path: $path}) RETURN n.id AS id",
        {"path": path},
    )
    ids = [r.get("id") for r in rows if isinstance(r.get("id"), str)]
    preserved: set[str] = set()
    for node_id in ids:
        if await node_has_human_edges(graph, node_id=node_id):
            preserved.add(node_id)
            await mark_human_edges_stale_for_node(
                graph, node_id=node_id, reason="file_deleted"
            )
    deletable = [node_id for node_id in ids if node_id not in preserved]
    await delete_nodes_by_ids(graph, deletable)


def _rewrite_id(value: str, *, old_path: str, new_path: str) -> str:
    return value.replace(old_path, new_path)


def _rewrite_node_for_rename(node: Node, *, old_path: str, new_path: str) -> Node:
    update: dict[str, Any] = {}
    if isinstance(node.id, str) and old_path in node.id:
        update["id"] = _rewrite_id(node.id, old_path=old_path, new_path=new_path)
    if isinstance(node.path, str) and node.path == old_path:
        update["path"] = new_path
    if isinstance(node.parent_id, str) and old_path in node.parent_id:
        update["parent_id"] = _rewrite_id(
            node.parent_id, old_path=old_path, new_path=new_path
        )
    return node if not update else node.model_copy(update=update)


def _rewrite_edge_for_rename(edge: Edge, *, old_path: str, new_path: str) -> Edge:
    update: dict[str, Any] = {}
    if isinstance(edge.from_id, str) and old_path in edge.from_id:
        update["from_id"] = _rewrite_id(
            edge.from_id, old_path=old_path, new_path=new_path
        )
    if isinstance(edge.to_id, str) and old_path in edge.to_id:
        update["to_id"] = _rewrite_id(edge.to_id, old_path=old_path, new_path=new_path)
    return edge if not update else edge.model_copy(update=update)


async def _get_nodes_by_path(graph: BulkGraph, *, path: str) -> list[Node]:
    rows = await graph.query(
        "MATCH (n {path: $path}) RETURN properties(n) AS props",
        {"path": path},
    )
    out: list[Node] = []
    for row in rows:
        props = row.get("props")
        if isinstance(props, dict):
            props = deserialize_node_props(props)
            out.append(Node.model_validate(props))
    return out


async def _finalize_upsert_nodes(
    repo_path: str,
    graph: BulkGraph,
    *,
    nodes_to_upsert: list[Node],
    warnings: list[str],
) -> None:
    if not nodes_to_upsert:
        return

    nodes_to_upsert[:] = await extract_summaries(nodes_to_upsert)
    nodes_to_upsert[:] = await embed_nodes(nodes_to_upsert)
    await graph.bulk_create_nodes(nodes_to_upsert)

    code_nodes = [
        node
        for node in nodes_to_upsert
        if node.source == NodeSource.CODE and node.kind != NodeKind.FILE
    ]
    if not code_nodes:
        return

    all_doc_nodes = await get_doc_nodes_for_linking(graph)
    # Only link markdown doc nodes — Jira ticket linking is handled by git_linker
    doc_nodes = [n for n in all_doc_nodes if not (n.path or "").startswith("jira://")]
    if not doc_nodes:
        return
    await SemanticLinker().link(code_nodes, doc_nodes, graph)


async def _finalize_upsert_edges(
    graph: BulkGraph,
    *,
    edges_to_upsert: list[Edge],
) -> None:
    if not edges_to_upsert:
        return
    await graph.bulk_create_edges(edges_to_upsert)


async def _count_graph(graph: BulkGraph) -> tuple[int, int]:
    rows = await graph.query("MATCH (n) RETURN count(n) AS c")
    node_count = int(rows[0]["c"]) if rows else 0
    rows = await graph.query("MATCH ()-[r]->() RETURN count(r) AS c")
    edge_count = int(rows[0]["c"]) if rows else 0
    return (node_count, edge_count)


async def _get_loom_implements_targets(graph: BulkGraph, *, node_id: str) -> list[str]:
    rows = await graph.query(
        f"MATCH (n {{id: $id}})-[:{LOOM_IMPLEMENTS_REL}]->(d) RETURN d.id AS id",
        {"id": node_id},
    )
    return [row.get("id") for row in rows if isinstance(row.get("id"), str)]


async def _finalize_incremental_updates(
    repo_path: str,
    graph: BulkGraph,
    *,
    t0: float,
    errors: list[IngestError],
    warnings: list[str],
    nodes_to_upsert: list[Node],
    edges_to_upsert: list[Edge],
    file_count: int,
    files_added: int,
    files_updated: int,
    files_deleted: int,
) -> IndexResult:
    await _finalize_upsert_nodes(
        repo_path,
        graph,
        nodes_to_upsert=nodes_to_upsert,
        warnings=warnings,
    )
    await _finalize_upsert_edges(graph, edges_to_upsert=edges_to_upsert)
    node_count, edge_count = await _count_graph(graph)

    return IndexResult(
        node_count=node_count,
        edge_count=edge_count,
        file_count=file_count,
        files_skipped=0,
        files_updated=files_updated,
        files_added=files_added,
        files_deleted=files_deleted,
        error_count=len(errors),
        duration_ms=(perf_counter() - t0) * 1000.0,
        errors=errors,
        warnings=warnings,
>>>>>>> main
    )


async def sync_paths(
    repo_path: str,
    changed_paths: list[str],
    graph: BulkGraph,
) -> IndexResult:
    t0 = perf_counter()
    errors: list[IngestError] = []
    warnings: list[str] = []
    files_added = 0
    files_updated = 0
    files_deleted = 0
    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    async def _sync_single_path(*, abs_path: str) -> tuple[int, int, int]:
        if not Path(abs_path).exists():
            await _handle_deleted_path(graph, path=abs_path, errors=errors)
            return (0, 0, 1)

        old_nodes = await _get_nodes_by_path(graph, path=abs_path)
        is_new_file = len(old_nodes) == 0

        await _sync_modified_path(
            abs_path=abs_path,
            graph=graph,
            errors=errors,
            warnings=warnings,
            nodes_to_upsert=nodes_to_upsert,
            edges_to_upsert=edges_to_upsert,
        )
        return (1, 0, 0) if is_new_file else (0, 1, 0)

    for raw_path in changed_paths:
        abs_path = Path(raw_path).resolve().as_posix()
        added, updated, deleted = await _sync_single_path(abs_path=abs_path)
        files_added += added
        files_updated += updated
        files_deleted += deleted

    return await _finalize_incremental_updates(
        repo_path,
        graph,
        t0=t0,
        errors=errors,
        warnings=warnings,
        nodes_to_upsert=nodes_to_upsert,
        edges_to_upsert=edges_to_upsert,
        file_count=len(changed_paths),
        files_added=files_added,
        files_updated=files_updated,
        files_deleted=files_deleted,
    )


async def _sync_added_path(
    *,
    abs_path: str,
    graph: BulkGraph,
    errors: list[IngestError],
    nodes_to_upsert: list[Node],
    edges_to_upsert: list[Edge],
) -> tuple[int, int]:
    if not Path(abs_path).exists():
        # File was added and immediately deleted before sync ran.
        # It was never indexed so there is nothing to invalidate.
        return (0, 0)
    new_nodes = await asyncio.to_thread(parse_code, abs_path)
    batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
    nodes_to_upsert.extend(batch_nodes)
    edges_to_upsert.extend(batch_edges)
    return (1, 0)


async def _sync_modified_path(
    *,
    abs_path: str,
    graph: BulkGraph,
    errors: list[IngestError],
    warnings: list[str],
    nodes_to_upsert: list[Node],
    edges_to_upsert: list[Edge],
) -> tuple[int, int]:
    if not Path(abs_path).exists():
        await _handle_deleted_path(graph, path=abs_path, errors=errors)
        return (0, 1)

    old_nodes = await _get_nodes_by_path(graph, path=abs_path)
    new_nodes = await asyncio.to_thread(parse_code, abs_path)
    batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)

    d = diff_nodes(old_nodes, new_nodes)

    drift_edges: list[Edge] = []
    for old_node, new_node in d.changed:
        drift = detect_ast_drift(old_node, new_node)
        if not drift.changed:
            continue
        doc_ids = await _get_loom_implements_targets(graph, node_id=old_node.id)
        if not doc_ids:
            continue
        warning = f"AST drift detected for {new_node.id}: {'; '.join(drift.reasons)}"
        warnings.append(warning)
        for doc_id in doc_ids:
            drift_edges.append(
                Edge(
                    from_id=new_node.id,
                    to_id=doc_id,
                    kind=EdgeType.LOOM_VIOLATES,
                    origin=EdgeOrigin.COMPUTED,
                    confidence=1.0,
                    link_method="ast_diff",
                    link_reason="; ".join(drift.reasons),
                    metadata={"reasons": drift.reasons},
                )
            )

    deletable: list[str] = []
    for n in d.deleted:
        if await node_has_human_edges(graph, node_id=n.id):
            await mark_human_edges_stale_for_node(
                graph, node_id=n.id, reason="source_changed"
            )
            continue
        deletable.append(n.id)
    await delete_nodes_by_ids(graph, deletable)

    nodes_to_upsert.extend(batch_nodes)
    edges_to_upsert.extend(drift_edges)
    edges_to_upsert.extend(batch_edges)

    await invalidate_edges_for_file(graph, path=abs_path)
    return (1, 0)


async def _sync_deleted_path(
    *,
    abs_path: str,
    graph: BulkGraph,
    errors: list[IngestError],
) -> int:
    await _handle_deleted_path(graph, path=abs_path, errors=errors)
    return 1


async def _sync_renamed_path(
    *,
    repo_path: str,
    abs_path: str,
    old_path: str | None,
    graph: BulkGraph,
    errors: list[IngestError],
    nodes_to_upsert: list[Node],
    edges_to_upsert: list[Edge],
) -> tuple[int, int]:
    old_abs = _normalized_changed_path(repo_path, old_path) if old_path else None

    old_nodes: list[Node] = []
    old_edges: list[dict[str, Any]] = []

    if old_abs is not None:
        old_nodes = await _get_nodes_by_path(graph, path=old_abs)
        old_edges = await _get_outgoing_human_edges(graph, path=old_abs)
        old_edges.extend(await _get_incoming_human_edges(graph, path=old_abs))
        await invalidate_edges_for_file(graph, path=old_abs)

    if Path(abs_path).exists():
        new_nodes = await asyncio.to_thread(parse_code, abs_path)
        batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
    else:
        if old_abs is None or not Path(old_abs).exists():
            append_index_error(
                errors,
                path=abs_path,
                phase="hash",
                error=FileNotFoundError(abs_path),
            )
            return (0, 0)
        old_content_nodes = await asyncio.to_thread(parse_code, old_abs)
        raw_nodes, raw_edges = _build_file_batch(old_abs, old_content_nodes)
        batch_nodes = [
            _rewrite_node_for_rename(n, old_path=old_abs, new_path=abs_path)
            for n in raw_nodes
        ]
        batch_edges = [
            _rewrite_edge_for_rename(e, old_path=old_abs, new_path=abs_path)
            for e in raw_edges
        ]

    await graph.bulk_create_nodes(batch_nodes)

    edges_to_upsert.extend(batch_edges)

    old_by_id = {n.id: n for n in old_nodes}
    new_by_hash = {
        n.content_hash: n.id
        for n in batch_nodes
        if isinstance(n.content_hash, str) and n.content_hash
    }
    matched_old_ids = {
        n.id
        for n in old_nodes
        if isinstance(n.content_hash, str) and n.content_hash in new_by_hash
    }

    for row in old_edges:
        from_id = row.get("from_id")
        to_id = row.get("to_id")
        rel_type = row.get("rel_type")
        props = row.get("props")
        if not (
            isinstance(from_id, str)
            and isinstance(to_id, str)
            and isinstance(rel_type, str)
            and isinstance(props, dict)
        ):
            continue
        props = deserialize_edge_props(dict(props))

        new_from = from_id
        if from_id in old_by_id:
            chash = old_by_id[from_id].content_hash
            if isinstance(chash, str) and chash in new_by_hash:
                new_from = new_by_hash[chash]

        new_to = to_id
        if to_id in old_by_id:
            chash = old_by_id[to_id].content_hash
            if isinstance(chash, str) and chash in new_by_hash:
                new_to = new_by_hash[chash]

        if new_from != from_id or new_to != to_id:
            await _create_edge(
                graph,
                from_id=new_from,
                to_id=new_to,
                rel_type=rel_type,
                props=props,
            )
        else:
            logger.warning(
                "HUMAN edge (%s)-[%s]->(%s) could not be migrated after rename "
                "of %r — no content-hash match found for either endpoint. Edge dropped.",
                from_id,
                rel_type,
                to_id,
                old_abs,
            )

    deletable_old_ids: list[str] = []
    for old_node in old_nodes:
        if old_node.id in matched_old_ids:
            deletable_old_ids.append(old_node.id)
            continue
        if await node_has_human_edges(graph, node_id=old_node.id):
            await mark_human_edges_stale_for_node(
                graph, node_id=old_node.id, reason="source_renamed"
            )
            continue
        deletable_old_ids.append(old_node.id)
    await delete_nodes_by_ids(graph, deletable_old_ids)

    nodes_to_upsert.extend(batch_nodes)
    return (1, 1)


async def sync_commits(
    repo_path: str,
    old_sha: str,
    new_sha: str,
    graph: BulkGraph,
) -> IndexResult:
    """Incrementally sync graph between two git SHAs.

    This is a pragmatic first cut:
    - Uses git diff to find changed files.
    - Re-parses only those files.
    - Applies a node-level diff by id/content_hash.
    - Uses origin-based edge invalidation for modified paths.

    Rename migration of HUMAN edges is best-effort: edges whose endpoints cannot be
    matched by content hash are dropped and a WARNING is emitted for each one.
    """

    t0 = perf_counter()
    errors: list[IngestError] = []
    warnings: list[str] = []

    changes = await get_changed_files(repo_path, old_sha, new_sha)

    files_added = 0
    files_updated = 0
    files_deleted = 0

    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    for ch in changes:
        abs_path = _normalized_changed_path(repo_path, ch.path)

        if ch.status == "A":
            added, deleted = await _sync_added_path(
                abs_path=abs_path,
                graph=graph,
                errors=errors,
                nodes_to_upsert=nodes_to_upsert,
                edges_to_upsert=edges_to_upsert,
            )
            files_added += added
            files_deleted += deleted

        elif ch.status == "M":
            updated, deleted = await _sync_modified_path(
                abs_path=abs_path,
                graph=graph,
                errors=errors,
                warnings=warnings,
                nodes_to_upsert=nodes_to_upsert,
                edges_to_upsert=edges_to_upsert,
            )
            files_updated += updated
            files_deleted += deleted

        elif ch.status == "D":
            files_deleted += await _sync_deleted_path(
                abs_path=abs_path,
                graph=graph,
                errors=errors,
            )

        elif ch.status == "R":
            added, deleted = await _sync_renamed_path(
                repo_path=repo_path,
                abs_path=abs_path,
                old_path=ch.old_path,
                graph=graph,
                errors=errors,
                nodes_to_upsert=nodes_to_upsert,
                edges_to_upsert=edges_to_upsert,
            )
            files_added += added
            files_deleted += deleted

    return await _finalize_incremental_updates(
        repo_path,
        graph,
        t0=t0,
        errors=errors,
        warnings=warnings,
        nodes_to_upsert=nodes_to_upsert,
        edges_to_upsert=edges_to_upsert,
        file_count=len(changes),
        files_added=files_added,
        files_updated=files_updated,
        files_deleted=files_deleted,
    )
