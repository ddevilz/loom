from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from loom.analysis.code.parser import parse_code
from loom.core import Edge, EdgeOrigin, EdgeType, LoomGraph, Node
from loom.core.falkor.mappers import deserialize_node_props
from loom.drift.detector import detect_ast_drift
from loom.ingest.differ import diff_nodes
from loom.ingest.git import FileChange, get_changed_files
from loom.ingest.pipeline import _invalidate_edges_for_file  # type: ignore[attr-defined]
from loom.ingest.result import IndexError, IndexResult


async def _get_outgoing_human_edges(graph: _Graph, *, path: str) -> list[dict[str, Any]]:
    return await graph.query(
        """
MATCH (a {path: $path})-[r]->(b)
WHERE r.origin = 'human'
RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, properties(r) AS props
""",
        {"path": path},
    )


async def _create_edge(
    graph: _Graph,
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


class _Graph(Protocol):
    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    async def bulk_create_nodes(self, nodes: list[Node]) -> None: ...

    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


async def _get_nodes_by_path(graph: _Graph, *, path: str) -> list[Node]:
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


async def _delete_nodes_by_ids(graph: _Graph, ids: list[str]) -> None:
    if not ids:
        return
    await graph.query(
        "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n",
        {"ids": ids},
    )


async def _mark_human_edges_stale_for_node(
    graph: _Graph,
    *,
    node_id: str,
    reason: str,
) -> None:
    await graph.query(
        """
MATCH (n {id: $id})-[r]->()
WHERE r.origin = 'human'
SET r.stale = true,
    r.stale_reason = $reason
""",
        {"id": node_id, "reason": reason},
    )


async def _node_has_human_edges(graph: _Graph, *, node_id: str) -> bool:
    rows = await graph.query(
        """
MATCH (n {id: $id})-[r]->()
WHERE r.origin = 'human'
RETURN count(r) AS c
""",
        {"id": node_id},
    )
    return bool(rows) and int(rows[0].get("c", 0)) > 0


async def _delete_nodes_by_path(graph: _Graph, *, path: str) -> None:
    await graph.query("MATCH (n {path: $path}) DETACH DELETE n", {"path": path})


async def _get_loom_implements_targets(graph: _Graph, *, node_id: str) -> list[str]:
    rows = await graph.query(
        "MATCH (n {id: $id})-[:LOOM_IMPLEMENTS]->(d) RETURN d.id AS id",
        {"id": node_id},
    )
    return [row.get("id") for row in rows if isinstance(row.get("id"), str)]


async def sync_commits(
    repo_path: str,
    old_sha: str,
    new_sha: str,
    graph: LoomGraph | _Graph,
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
            errors=[IndexError(path=repo_path, phase="summarize", message=str(e))],
            warnings=[],
        )

    files_added = 0
    files_updated = 0
    files_deleted = 0

    nodes_to_upsert: list[Node] = []
    edges_to_upsert: list[Edge] = []

    for ch in changes:
        abs_path = str(Path(repo_path) / ch.path)

        if ch.status == "A":
            files_added += 1
            try:
                nodes_to_upsert.extend(parse_code(abs_path))
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="parse", message=str(e)))

        elif ch.status == "M":
            files_updated += 1
            try:
                old_nodes = await _get_nodes_by_path(graph, path=abs_path)
            except Exception as e:
                old_nodes = []
                errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))

            try:
                new_nodes = parse_code(abs_path)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="parse", message=str(e)))
                continue

            d = diff_nodes(old_nodes, new_nodes)

            drift_edges: list[Edge] = []
            for old_node, new_node in d.changed:
                drift = detect_ast_drift(old_node, new_node)
                if not drift.changed:
                    continue
                try:
                    doc_ids = await _get_loom_implements_targets(graph, node_id=old_node.id)
                except Exception as e:
                    errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))
                    doc_ids = []
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

            # Remove deleted nodes.
            try:
                deletable: list[str] = []
                for n in d.deleted:
                    if await _node_has_human_edges(graph, node_id=n.id):
                        await _mark_human_edges_stale_for_node(
                            graph, node_id=n.id, reason="source_changed"
                        )
                        continue
                    deletable.append(n.id)
                await _delete_nodes_by_ids(graph, deletable)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))

            # Upsert new/changed nodes.
            nodes_to_upsert.extend(d.added)
            nodes_to_upsert.extend([n for (_, n) in d.changed])
            edges_to_upsert.extend(drift_edges)

            # Invalidate edges based on origin rules for this file.
            try:
                await _invalidate_edges_for_file(graph, path=abs_path)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))

        elif ch.status == "D":
            files_deleted += 1
            try:
                # Preserve HUMAN edges: flag stale instead of deleting.
                rows = await graph.query(
                    "MATCH (n {path: $path}) RETURN n.id AS id",
                    {"path": abs_path},
                )
                ids = [r.get("id") for r in rows if isinstance(r.get("id"), str)]
                preserved = []
                for node_id in ids:
                    if await _node_has_human_edges(graph, node_id=node_id):
                        preserved.append(node_id)
                        await _mark_human_edges_stale_for_node(
                            graph, node_id=node_id, reason="file_deleted"
                        )
                deletable = [i for i in ids if i not in set(preserved)]
                await _delete_nodes_by_ids(graph, deletable)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))

        elif ch.status == "R":
            files_deleted += 1
            files_added += 1

            old_abs = str(Path(repo_path) / (ch.old_path or ""))

            try:
                old_nodes = await _get_nodes_by_path(graph, path=old_abs)
                old_edges = await _get_outgoing_human_edges(graph, path=old_abs)
            except Exception as e:
                old_nodes = []
                old_edges = []
                errors.append(IndexError(path=old_abs, phase="persist", message=str(e)))

            try:
                new_nodes = parse_code(abs_path)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="parse", message=str(e)))
                continue

            # Upsert new nodes immediately so we can recreate migrated edges.
            try:
                await graph.bulk_create_nodes(new_nodes)
            except Exception as e:
                errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))
                continue

            old_by_id = {n.id: n for n in old_nodes}
            old_by_hash = {
                n.content_hash: n.id
                for n in old_nodes
                if isinstance(n.content_hash, str) and n.content_hash
            }
            new_by_hash = {
                n.content_hash: n.id
                for n in new_nodes
                if isinstance(n.content_hash, str) and n.content_hash
            }

            # Migrate outgoing HUMAN edges when endpoint nodes match by content_hash.
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
                        errors.append(IndexError(path=abs_path, phase="persist", message=str(e)))

            # Remove old nodes after migration.
            try:
                if ch.old_path:
                    await _delete_nodes_by_path(graph, path=old_abs)
            except Exception as e:
                errors.append(IndexError(path=old_abs, phase="persist", message=str(e)))

    if nodes_to_upsert:
        try:
            await graph.bulk_create_nodes(nodes_to_upsert)
        except Exception as e:
            errors.append(IndexError(path=repo_path, phase="persist", message=str(e)))

    if edges_to_upsert:
        try:
            await graph.bulk_create_edges(edges_to_upsert)
        except Exception as e:
            errors.append(IndexError(path=repo_path, phase="persist", message=str(e)))

    node_count = 0
    edge_count = 0
    try:
        rows = await graph.query("MATCH (n) RETURN count(n) AS c")
        node_count = int(rows[0]["c"]) if rows else 0
        rows = await graph.query("MATCH ()-[r]->() RETURN count(r) AS c")
        edge_count = int(rows[0]["c"]) if rows else 0
    except Exception as e:
        errors.append(IndexError(path=repo_path, phase="summarize", message=str(e)))

    return IndexResult(
        node_count=node_count,
        edge_count=edge_count,
        file_count=len(changes),
        files_skipped=0,
        files_updated=files_updated,
        files_added=files_added,
        files_deleted=files_deleted,
        error_count=len(errors),
        duration_ms=(perf_counter() - t0) * 1000.0,
        errors=errors,
        warnings=warnings,
    )
