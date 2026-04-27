from __future__ import annotations

import asyncio
import functools
import json
import logging
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

from loom.analysis.code.calls.python import (
    _build_symbol_map,
    trace_calls_for_file_with_global_symbols,
)
from loom.analysis.communities import compute_communities
from loom.analysis.code.extractor import extract_summary
from loom.analysis.coupling import compute_coupling
from loom.analysis.dead_code import mark_dead_code
from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.ingest.code.languages.constants import EXT_PY, EXT_PYW
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo
from loom.ingest.utils import sha256_of_file
from loom.store import nodes as node_store
from loom.store.nodes import mark_nodes_deleted, prune_tombstones
from loom.store.sessions import prune_sessions
from loom.analysis.code.parser import parse_code

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class IndexResult:
    repo_path: Path
    files_parsed: int
    files_skipped: int
    nodes_written: int
    edges_written: int
    errors: list[str] = field(default_factory=list)


def _remap_id(old_id: str, abs_path: str, rel_path: str) -> str:
    if f":{abs_path}:" in old_id:
        return old_id.replace(f":{abs_path}:", f":{rel_path}:", 1)
    if old_id.endswith(f":{abs_path}"):
        return old_id[: -len(abs_path)] + rel_path
    return old_id


def _get_call_tracer(abs_path: str):  # type: ignore[return]
    handler = get_registry().get_handler_for_path(abs_path)
    if handler is None:
        return None
    return handler.call_tracer


def _parse_file(file_path: Path, *, repo_root: Path) -> ParseResult:
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

    id_map: dict[str, str] = {}
    for n in raw_nodes:
        new_id = _remap_id(n.id, abs_path, rel_path)
        id_map[n.id] = new_id

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

    nodes: list[Node] = [file_node]
    for n in raw_nodes:
        if n.kind == NodeKind.FILE:
            continue
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

    tracer = _get_call_tracer(abs_path)
    raw_edges: list[Edge] = []
    if tracer is not None:
        try:
            raw_edges = tracer(abs_path, raw_nodes)
        except Exception as exc:
            logger.warning("call tracer failed for %s: %s", rel_path, exc)

    contains_edges = [
        Edge(
            from_id=file_node_id,
            to_id=id_map.get(n.id, _remap_id(n.id, abs_path, rel_path)),
            kind=EdgeType.CONTAINS,
            confidence=1.0,
        )
        for n in raw_nodes
        if n.kind != NodeKind.FILE and n.parent_id is None
    ]

    edges: list[Edge] = list(contains_edges)
    for e in raw_edges:
        new_from = id_map.get(e.from_id, _remap_id(e.from_id, abs_path, rel_path))
        new_to = id_map.get(e.to_id, e.to_id)
        edges.append(e.model_copy(update={"from_id": new_from, "to_id": new_to}))

    return ParseResult(nodes=nodes, edges=edges)


def resolve_calls(
    nodes: list[Node], edges: list[Edge], repo_root: Path
) -> tuple[list[Node], list[Edge]]:
    """Enhance cross-file CALLS resolution for Python using a global symbol map."""
    global_symbol_map = _build_symbol_map(nodes)
    if not global_symbol_map:
        return nodes, edges

    by_path: dict[str, list[Node]] = {}
    for n in nodes:
        if n.path:
            by_path.setdefault(n.path, []).append(n)

    python_source_ids: set[str] = set()
    global_call_edges: list[Edge] = []

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

    if not global_call_edges:
        return nodes, edges

    filtered = [
        e for e in edges
        if not (e.kind == EdgeType.CALLS and e.from_id in python_source_ids)
    ]
    return nodes, filtered + global_call_edges


async def index_repo(
    repo_path: Path,
    db: DB,
    *,
    workers: int | None = None,
) -> IndexResult:
    t0 = time.perf_counter()
    repo_path = repo_path.resolve()

    # --- Phase 1: scan ---
    logger.info("[scan] discovering files in %s", repo_path)
    t = time.perf_counter()
    files_by_lang = walk_repo(str(repo_path))
    all_files: list[Path] = [
        Path(fp) for fps in files_by_lang.values() for fp in fps
    ]
    existing = await node_store.get_content_hashes(db)
    changed: list[Path] = []
    skipped = 0
    for f in all_files:
        rel = f.relative_to(repo_path).as_posix()
        if sha256_of_file(f) == existing.get(rel):
            skipped += 1
        else:
            changed.append(f)
    logger.info(
        "[scan] done in %.1fs — %d total, %d changed, %d skipped",
        time.perf_counter() - t, len(all_files), len(changed), skipped,
    )

    nodes_all: list[Node] = []
    edges_all: list[Edge] = []
    errors: list[str] = []

    max_workers = workers or min(cpu_count(), 8)

    # --- Phase 2: parse ---
    if changed:
        logger.info("[parse] parsing %d files with %d workers", len(changed), max_workers)
        t = time.perf_counter()
        if len(changed) >= 8:
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
        logger.info(
            "[parse] done in %.1fs — %d nodes, %d edges",
            time.perf_counter() - t, len(nodes_all), len(edges_all),
        )
    else:
        logger.info("[parse] nothing to parse (all %d files unchanged)", skipped)

    # --- Phase 3: resolve cross-file calls ---
    logger.info("[calls] resolving cross-file call edges")
    t = time.perf_counter()
    nodes_all, edges_all = resolve_calls(nodes_all, edges_all, repo_path)
    logger.info("[calls] done in %.1fs — %d total edges", time.perf_counter() - t, len(edges_all))

    # --- Phase 4: write to DB ---
    by_path: dict[str, tuple[list[Node], list[Edge]]] = {}
    for n in nodes_all:
        if n.path not in by_path:
            by_path[n.path] = ([], [])
        by_path[n.path][0].append(n)

    for e in edges_all:
        src_path = ""
        if e.from_id.count(":") >= 2:
            src_path = e.from_id.split(":", 2)[1]
        elif e.from_id.startswith("file:"):
            src_path = e.from_id[5:]
        if src_path in by_path:
            by_path[src_path][1].append(e)

    if by_path:
        logger.info("[write] writing %d paths to DB", len(by_path))
        t = time.perf_counter()
        for path, (fn, fe) in by_path.items():
            await node_store.replace_file(db, path, fn, fe)
        logger.info("[write] done in %.1fs", time.perf_counter() - t)

    # --- Phase 5: communities ---
    logger.info("[communities] computing Louvain communities")
    t = time.perf_counter()
    try:
        await compute_communities(db)
        logger.info("[communities] done in %.1fs", time.perf_counter() - t)
    except Exception as exc:
        logger.warning("[communities] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 6: coupling ---
    logger.info("[coupling] computing git co-change coupling")
    t = time.perf_counter()
    try:
        await compute_coupling(db, repo_path)
        logger.info("[coupling] done in %.1fs", time.perf_counter() - t)
    except Exception as exc:
        logger.warning("[coupling] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 7: dead code ---
    logger.info("[dead_code] marking dead code")
    t = time.perf_counter()
    try:
        await mark_dead_code(db)
        logger.info("[dead_code] done in %.1fs", time.perf_counter() - t)
    except Exception as exc:
        logger.warning("[dead_code] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 8: auto-summaries ---
    logger.info("[summaries] generating auto-summaries for unsummarized nodes")
    t = time.perf_counter()
    try:
        filled = await _fill_auto_summaries(db)
        logger.info("[summaries] done in %.1fs — %d summaries written", time.perf_counter() - t, filled)
    except Exception as exc:
        logger.warning("[summaries] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 9: soft-delete removed files ---
    try:
        current_rel_paths: set[str] = {
            f.relative_to(repo_path).as_posix() for f in all_files
        }
        def _get_indexed_paths() -> list[str]:
            with db._lock:
                conn = db.connect()
                return [
                    r["path"] for r in conn.execute(
                        "SELECT DISTINCT path FROM nodes WHERE kind = 'file' AND deleted_at IS NULL"
                    ).fetchall()
                ]
        indexed_paths = await asyncio.to_thread(_get_indexed_paths)
        deleted_count = 0
        for ipath in indexed_paths:
            if ipath not in current_rel_paths:
                await mark_nodes_deleted(db, ipath)
                deleted_count += 1
        if deleted_count:
            logger.info("[cleanup] soft-deleted %d removed files", deleted_count)
        await prune_tombstones(db)
    except Exception as exc:
        logger.warning("[cleanup] deleted_file_detection failed: %s", exc)

    # --- Phase 10: prune sessions ---
    try:
        await prune_sessions(db, keep=20)
    except Exception as exc:
        logger.warning("[cleanup] prune_sessions failed: %s", exc)

    elapsed = time.perf_counter() - t0
    logger.info(
        "[done] total %.1fs — %d files parsed, %d nodes, %d edges",
        elapsed, len(changed), len(nodes_all), len(edges_all),
    )

    return IndexResult(
        repo_path=repo_path,
        files_parsed=len(changed),
        files_skipped=skipped,
        nodes_written=len(nodes_all),
        edges_written=len(edges_all),
        errors=errors,
    )


async def _fill_auto_summaries(db: DB) -> int:
    """Fill summary for nodes that have none, using static metadata extraction.

    Only fills NULL summaries — never overwrites agent-written summaries.

    Args:
        db: Database context.

    Returns:
        Number of nodes updated.
    """
    def _get_null_summary_nodes() -> list[sqlite3.Row]:
        with db._lock:
            conn = db.connect()
            return conn.execute(
                "SELECT id, kind, name, path, language, metadata "
                "FROM nodes WHERE summary IS NULL AND kind NOT IN ('file', 'community') "
                "AND deleted_at IS NULL"
            ).fetchall()

    rows = await asyncio.to_thread(_get_null_summary_nodes)
    if not rows:
        return 0

    updates: list[tuple[str, str]] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            n = Node(
                id=row["id"],
                kind=NodeKind(row["kind"]),
                source=NodeSource.CODE,
                name=row["name"],
                path=row["path"],
                language=row["language"],
                metadata=metadata,
            )
            auto = extract_summary(n)
            if auto and auto.strip():
                updates.append((auto, row["id"]))
        except Exception as exc:
            logger.warning("auto_summary failed for %s: %s", row["id"], exc)
            continue

    if not updates:
        return 0

    def _write(items: list[tuple[str, str]]) -> int:
        with db._lock:
            conn = db.connect()
            conn.executemany(
                "UPDATE nodes SET summary = ? WHERE id = ? AND summary IS NULL",
                items,
            )
            conn.commit()
            return len(items)

    return await asyncio.to_thread(_write, updates)
