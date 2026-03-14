from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter
from typing import Any

from loom.analysis.code.extractor import extract_summaries
from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
from loom.core.falkor.mappers import deserialize_edge_props, deserialize_node_props
from loom.core.protocols import BulkGraph
from loom.drift.detector import detect_ast_drift
from loom.embed.embedder import embed_nodes
from loom.ingest.code.registry import get_registry
from loom.ingest.differ import diff_nodes
from loom.ingest.errors import append_index_error
from loom.ingest.git import get_changed_files
from loom.ingest.helpers import build_contains_edges, make_file_node
from loom.ingest.result import IndexError, IndexResult
from loom.ingest.utils import (
    delete_nodes_by_ids,
    get_doc_nodes_for_linking,
    invalidate_edges_for_file,
    mark_human_edges_stale_for_node,
    node_has_human_edges,
)
from loom.linker.linker import SemanticLinker

_LOOM_IMPL_REL = EdgeTypeAdapter.to_storage(EdgeType.LOOM_IMPLEMENTS)


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
    )


async def _create_edge(
    graph: BulkGraph,
    *,
    from_id: str,
    to_id: str,
    rel_type: str,
    props: dict[str, Any],
) -> None:
    # Relationship type can't be parameterized.
    await graph.query(
        f"MATCH (a {{id: $from_id}}), (b {{id: $to_id}}) MERGE (a)-[r:`{rel_type}`]->(b) SET r += $props",
        {"from_id": from_id, "to_id": to_id, "props": props},
    )


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
            try:
                out.append(Node.model_validate(props))
            except Exception:
                continue
    return out


async def _get_loom_implements_targets(graph: BulkGraph, *, node_id: str) -> list[str]:
    rows = await graph.query(
        f"MATCH (n {{id: $id}})-[:{_LOOM_IMPL_REL}]->(d) RETURN d.id AS id",
        {"id": node_id},
    )
    return [row.get("id") for row in rows if isinstance(row.get("id"), str)]


async def _finalize_incremental_updates(
    repo_path: str,
    graph: BulkGraph,
    *,
    t0: float,
    errors: list[IndexError],
    warnings: list[str],
    nodes_to_upsert: list[Node],
    edges_to_upsert: list[Edge],
    file_count: int,
    files_added: int,
    files_updated: int,
    files_deleted: int,
) -> IndexResult:
    if nodes_to_upsert:
        try:
            nodes_to_upsert = await extract_summaries(nodes_to_upsert)
        except Exception as e:
            append_index_error(errors, path=repo_path, phase="summarize", error=e)

        try:
            nodes_to_upsert = await embed_nodes(nodes_to_upsert)
        except Exception as e:
            append_index_error(errors, path=repo_path, phase="embed", error=e)

        try:
            await graph.bulk_create_nodes(nodes_to_upsert)
        except Exception as e:
            append_index_error(errors, path=repo_path, phase="persist", error=e)

        code_nodes = [
            node
            for node in nodes_to_upsert
            if node.source == NodeSource.CODE and node.kind != NodeKind.FILE
        ]
        if code_nodes:
            try:
                doc_nodes = await get_doc_nodes_for_linking(graph)
            except Exception as e:
                append_index_error(errors, path=repo_path, phase="link", error=e)
                doc_nodes = []
            if doc_nodes:
                try:
                    await SemanticLinker().link(code_nodes, doc_nodes, graph)
                except Exception as e:
                    append_index_error(errors, path=repo_path, phase="link", error=e)

    if edges_to_upsert:
        try:
            await graph.bulk_create_edges(edges_to_upsert)
        except Exception as e:
            append_index_error(errors, path=repo_path, phase="persist", error=e)

    node_count = 0
    edge_count = 0
    try:
        rows = await graph.query("MATCH (n) RETURN count(n) AS c")
        node_count = int(rows[0]["c"]) if rows else 0
        rows = await graph.query("MATCH ()-[r]->() RETURN count(r) AS c")
        edge_count = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        append_index_error(errors, path=repo_path, phase="persist", error=e)

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
    )


async def sync_paths(
    repo_path: str,
    changed_paths: list[str],
    graph: BulkGraph,
) -> IndexResult:
    t0 = perf_counter()
    errors: list[IndexError] = []
    warnings: list[str] = []
    files_added = 0
    files_updated = 0
    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    for raw_path in changed_paths:
        abs_path = Path(raw_path).resolve().as_posix()

        try:
            old_nodes = await _get_nodes_by_path(graph, path=abs_path)
        except Exception as e:
            append_index_error(errors, path=abs_path, phase="persist", error=e)
            old_nodes = []

        if old_nodes:
            files_updated += 1
        else:
            files_added += 1

        try:
            new_nodes = await asyncio.to_thread(parse_code, abs_path)
            batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
        except Exception as e:
            append_index_error(
                errors,
                path=abs_path,
                phase="hash" if isinstance(e, OSError) else "parse",
                error=e,
            )
            continue

        if old_nodes:
            d = diff_nodes(old_nodes, new_nodes)

            drift_edges: list[Edge] = []
            for old_node, new_node in d.changed:
                drift = detect_ast_drift(old_node, new_node)
                if not drift.changed:
                    continue
                try:
                    doc_ids = await _get_loom_implements_targets(
                        graph, node_id=old_node.id
                    )
                except Exception as e:
                    append_index_error(errors, path=abs_path, phase="persist", error=e)
                    doc_ids = []
                if not doc_ids:
                    continue
                warnings.append(
                    f"AST drift detected for {new_node.id}: {'; '.join(drift.reasons)}"
                )
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

            try:
                deletable: list[str] = []
                for n in d.deleted:
                    if await node_has_human_edges(graph, node_id=n.id):
                        await mark_human_edges_stale_for_node(
                            graph, node_id=n.id, reason="source_changed"
                        )
                        continue
                    deletable.append(n.id)
                await delete_nodes_by_ids(graph, deletable)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)

            try:
                await invalidate_edges_for_file(graph, path=abs_path)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)

            edges_to_upsert.extend(drift_edges)

        nodes_to_upsert.extend(batch_nodes)
        edges_to_upsert.extend(batch_edges)

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
        files_deleted=0,
    )


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

    Rename migration of HUMAN edges is best-effort and not fully implemented yet.
    """

    t0 = perf_counter()
    errors: list[IndexError] = []
    warnings: list[str] = []

    try:
        changes = await get_changed_files(repo_path, old_sha, new_sha)
    except Exception as e:
        return IndexResult(
            node_count=0,
            edge_count=0,
            file_count=0,
            files_skipped=0,
            files_updated=0,
            files_added=0,
            files_deleted=0,
            error_count=1,
            duration_ms=(perf_counter() - t0) * 1000.0,
            errors=[IndexError(path=repo_path, phase="process", message=str(e))],
            warnings=[],
        )

    files_added = 0
    files_updated = 0
    files_deleted = 0

    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    for ch in changes:
        abs_path = _normalized_changed_path(repo_path, ch.path)

        if ch.status == "A":
            files_added += 1
            try:
                new_nodes = await asyncio.to_thread(parse_code, abs_path)
                batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
                nodes_to_upsert.extend(batch_nodes)
                edges_to_upsert.extend(batch_edges)
            except Exception as e:
                append_index_error(
                    errors,
                    path=abs_path,
                    phase="hash" if isinstance(e, OSError) else "parse",
                    error=e,
                )

        elif ch.status == "M":
            files_updated += 1
            try:
                old_nodes = await _get_nodes_by_path(graph, path=abs_path)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)
                old_nodes = []

            try:
                new_nodes = await asyncio.to_thread(parse_code, abs_path)
                batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
            except Exception as e:
                append_index_error(
                    errors,
                    path=abs_path,
                    phase="hash" if isinstance(e, OSError) else "parse",
                    error=e,
                )
                continue

            d = diff_nodes(old_nodes, new_nodes)

            drift_edges: list[Edge] = []
            for old_node, new_node in d.changed:
                drift = detect_ast_drift(old_node, new_node)
                if not drift.changed:
                    continue
                try:
                    doc_ids = await _get_loom_implements_targets(
                        graph, node_id=old_node.id
                    )
                except Exception as e:
                    append_index_error(errors, path=abs_path, phase="persist", error=e)
                    doc_ids = []
                if not doc_ids:
                    continue
                warning = (
                    f"AST drift detected for {new_node.id}: {'; '.join(drift.reasons)}"
                )
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

            # Remove deleted nodes.
            try:
                deletable: list[str] = []
                for n in d.deleted:
                    if await node_has_human_edges(graph, node_id=n.id):
                        await mark_human_edges_stale_for_node(
                            graph, node_id=n.id, reason="source_changed"
                        )
                        continue
                    deletable.append(n.id)
                await delete_nodes_by_ids(graph, deletable)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)

            # Upsert new/changed nodes.
            nodes_to_upsert.extend(batch_nodes)
            edges_to_upsert.extend(drift_edges)
            edges_to_upsert.extend(batch_edges)

            # Invalidate edges based on origin rules for this file.
            try:
                await invalidate_edges_for_file(graph, path=abs_path)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)

        elif ch.status == "D":
            files_deleted += 1
            try:
                await invalidate_edges_for_file(graph, path=abs_path)

                # Preserve HUMAN edges: flag stale instead of deleting.
                rows = await graph.query(
                    "MATCH (n {path: $path}) RETURN n.id AS id",
                    {"path": abs_path},
                )
                ids = [r.get("id") for r in rows if isinstance(r.get("id"), str)]
                preserved = []
                for node_id in ids:
                    if await node_has_human_edges(graph, node_id=node_id):
                        preserved.append(node_id)
                        await mark_human_edges_stale_for_node(
                            graph, node_id=node_id, reason="file_deleted"
                        )
                deletable = [i for i in ids if i not in set(preserved)]
                await delete_nodes_by_ids(graph, deletable)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)

        elif ch.status == "R":
            files_deleted += 1
            files_added += 1

            old_nodes: list[Node] = []
            old_edges: list[dict[str, Any]] = []
            old_abs = (
                _normalized_changed_path(repo_path, ch.old_path)
                if ch.old_path
                else None
            )

            if old_abs is not None:
                try:
                    old_nodes = await _get_nodes_by_path(graph, path=old_abs)
                except Exception as e:
                    append_index_error(errors, path=old_abs, phase="persist", error=e)

                try:
                    old_edges = await _get_outgoing_human_edges(graph, path=old_abs)
                except Exception as e:
                    append_index_error(errors, path=old_abs, phase="persist", error=e)
                try:
                    old_edges.extend(
                        await _get_incoming_human_edges(graph, path=old_abs)
                    )
                except Exception as e:
                    append_index_error(errors, path=old_abs, phase="persist", error=e)
                try:
                    await invalidate_edges_for_file(graph, path=old_abs)
                except Exception as e:
                    append_index_error(errors, path=old_abs, phase="persist", error=e)

            try:
                new_nodes = await asyncio.to_thread(parse_code, abs_path)
                batch_nodes, batch_edges = _build_file_batch(abs_path, new_nodes)
            except Exception as e:
                append_index_error(
                    errors,
                    path=abs_path,
                    phase="hash" if isinstance(e, OSError) else "parse",
                    error=e,
                )
                continue

            # Upsert new nodes immediately so we can recreate migrated edges.
            try:
                await graph.bulk_create_nodes(batch_nodes)
            except Exception as e:
                append_index_error(errors, path=abs_path, phase="persist", error=e)
                continue

            # Note: batch_nodes already persisted above
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

            # Migrate HUMAN edges when endpoint nodes match by content_hash.
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

                # Only migrate if at least one endpoint moved to new ids.
                if new_from != from_id or new_to != to_id:
                    try:
                        await _create_edge(
                            graph,
                            from_id=new_from,
                            to_id=new_to,
                            rel_type=rel_type,
                            props=props,
                        )
                    except Exception as e:
                        append_index_error(
                            errors, path=abs_path, phase="persist", error=e
                        )

            # Remove only old nodes that are safe to delete after migration.
            try:
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
            except Exception as e:
                append_index_error(
                    errors,
                    path=old_abs if old_abs is not None else abs_path,
                    phase="persist",
                    error=e,
                )

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
