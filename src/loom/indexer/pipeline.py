"""pipeline.py — main indexing pipeline.

Moved from ingest/pipeline.py with the following changes:
- Imports updated to graph.* and indexer.*
- Internal store calls converted: await async_fn(db, ...) → await asyncio.to_thread(repo.method, ...)
- Signature changed: index_repo(repo_path, *, repo: Repository, ...) instead of (repo_path, db: DB, ...)
- index_repo() stays async def — callers already use asyncio.run() or await
- Communities/coupling/dead_code stay on old paths until Phase 3 (intelligence/) moves them
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

from loom.graph.models import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.graph.repository import Repository
from loom.indexer.extractor import extract_summary, parse_code
from loom.indexer.registry import get_registry
from loom.indexer.utils import sha256_of_file
from loom.indexer.walker import walk_repo
from loom.indexer.languages.constants import EXT_PY, EXT_PYW

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


def _hash_file(f: Path) -> tuple[Path, str, float]:
    return f, sha256_of_file(f), f.stat().st_mtime


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
        st = file_path.stat()
        file_hash = sha256_of_file(file_path)
        file_mtime = st.st_mtime
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
        file_mtime=file_mtime,
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
    from loom.indexer.calls.python import (
        _build_symbol_map,
        trace_calls_for_file_with_global_symbols,
    )

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
        e for e in edges if not (e.kind == EdgeType.CALLS and e.from_id in python_source_ids)
    ]
    return nodes, filtered + global_call_edges


async def index_repo(
    repo_path: Path,
    repo: Repository,
    *,
    workers: int | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> IndexResult:
    t0 = time.perf_counter()
    repo_path = repo_path.resolve()
    max_workers = workers or min(cpu_count(), 8)

    def _emit(phase: str, done: int, total: int) -> None:
        if progress_cb is not None:
            with contextlib.suppress(Exception):
                progress_cb(phase, done, total)

    # --- Phase 1: scan ---
    logger.info("[scan] discovering files in %s (workers=%d)", repo_path, max_workers)
    t = time.perf_counter()
    files_by_lang = walk_repo(str(repo_path))
    all_files: list[Path] = [Path(fp) for fps in files_by_lang.values() for fp in fps]
    existing = await asyncio.to_thread(repo.nodes.get_content_hashes)

    needs_hash: list[Path] = []
    changed: list[Path] = []
    skipped = 0
    for f in all_files:
        rel = f.relative_to(repo_path).as_posix()
        stored = existing.get(rel)
        if stored is not None:
            stored_hash, stored_mtime = stored
            if stored_mtime is not None and f.stat().st_mtime == stored_mtime:
                skipped += 1
                continue
        needs_hash.append(f)

    mtime_map: dict[str, float] = {}
    if needs_hash:
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            for f, h, mtime in pool.map(_hash_file, needs_hash, chunksize=50):
                rel = f.relative_to(repo_path).as_posix()
                mtime_map[rel] = mtime
                stored = existing.get(rel)
                stored_hash = stored[0] if stored else None
                if h == stored_hash:
                    skipped += 1
                else:
                    changed.append(f)
    logger.info(
        "[scan] done in %.1fs — %d total, %d changed, %d skipped",
        time.perf_counter() - t,
        len(all_files),
        len(changed),
        skipped,
    )
    _emit("scan", len(changed), len(all_files))

    nodes_all: list[Node] = []
    edges_all: list[Edge] = []
    errors: list[str] = []

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
            time.perf_counter() - t,
            len(nodes_all),
            len(edges_all),
        )
        _emit("parse", len(changed), len(changed))
    else:
        logger.info("[parse] nothing to parse (all %d files unchanged)", skipped)
        _emit("parse", 0, 0)

    # --- Phase 3: resolve cross-file calls ---
    if nodes_all:
        logger.info("[calls] resolving cross-file call edges")
        t = time.perf_counter()
        nodes_all, edges_all = resolve_calls(nodes_all, edges_all, repo_path)
        elapsed = time.perf_counter() - t
        logger.info("[calls] done in %.1fs — %d total edges", elapsed, len(edges_all))

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
            await asyncio.to_thread(repo.nodes.upsert, fn, fe, path)
        logger.info("[write] done in %.1fs", time.perf_counter() - t)
    _emit("write", len(by_path), len(by_path))

    if not changed:
        logger.info("[skip] no files changed — skipping analysis phases")
    else:
        # --- Phase 5: communities (still on old path until Phase 3) ---
        logger.info("[communities] computing Louvain communities")
        t = time.perf_counter()
        try:
            from loom.intelligence.communities import compute_communities  # noqa: PLC0415
            await compute_communities(repo.db)
            logger.info("[communities] done in %.1fs", time.perf_counter() - t)
        except Exception as exc:
            logger.warning("[communities] failed in %.1fs: %s", time.perf_counter() - t, exc)
        _emit("communities", 1, 1)

        # --- Phase 6: coupling ---
        logger.info("[coupling] computing git co-change coupling")
        t = time.perf_counter()
        try:
            from loom.intelligence.coupling import compute_coupling  # noqa: PLC0415
            await compute_coupling(repo.db, repo_path)
            logger.info("[coupling] done in %.1fs", time.perf_counter() - t)
        except Exception as exc:
            logger.warning("[coupling] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 7: dead code ---
        logger.info("[dead_code] marking dead code")
        t = time.perf_counter()
        try:
            from loom.intelligence.dead_code import mark_dead_code  # noqa: PLC0415
            await mark_dead_code(repo.db)
            logger.info("[dead_code] done in %.1fs", time.perf_counter() - t)
        except Exception as exc:
            logger.warning("[dead_code] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 8: auto-summaries ---
        logger.info("[summaries] generating auto-summaries for unsummarized nodes")
        t = time.perf_counter()
        try:
            filled = await _fill_auto_summaries(repo)
            elapsed = time.perf_counter() - t
            logger.info("[summaries] done in %.1fs — %d summaries written", elapsed, filled)
        except Exception as exc:
            logger.warning("[summaries] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 9: soft-delete removed files ---
    try:
        current_rel_paths: set[str] = {f.relative_to(repo_path).as_posix() for f in all_files}

        def _get_indexed_paths() -> list[str]:
            with repo.db._lock:
                conn = repo.db.connect()
                return [
                    r["path"]
                    for r in conn.execute(
                        "SELECT DISTINCT path FROM nodes WHERE kind = 'file' AND deleted_at IS NULL"
                    ).fetchall()
                ]

        indexed_paths = await asyncio.to_thread(_get_indexed_paths)
        deleted_count = 0
        for ipath in indexed_paths:
            if ipath not in current_rel_paths:
                await asyncio.to_thread(repo.nodes.mark_deleted, ipath)
                deleted_count += 1
        if deleted_count:
            logger.info("[cleanup] soft-deleted %d removed files", deleted_count)
        await asyncio.to_thread(repo.nodes.prune_tombstones)
    except Exception as exc:
        logger.warning("[cleanup] deleted_file_detection failed: %s", exc)

    # --- Phase 10: prune sessions ---
    try:
        await asyncio.to_thread(repo.sessions.prune, 20)
    except Exception as exc:
        logger.warning("[cleanup] prune_sessions failed: %s", exc)

    elapsed = time.perf_counter() - t0
    logger.info(
        "[done] total %.1fs — %d files parsed, %d nodes, %d edges",
        elapsed,
        len(changed),
        len(nodes_all),
        len(edges_all),
    )
    _emit("done", len(changed), len(all_files))

    return IndexResult(
        repo_path=repo_path,
        files_parsed=len(changed),
        files_skipped=skipped,
        nodes_written=len(nodes_all),
        edges_written=len(edges_all),
        errors=errors,
    )


async def _fill_auto_summaries(repo: Repository) -> int:
    """Fill summary for nodes that have none, using static metadata extraction."""
    db = repo.db

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
