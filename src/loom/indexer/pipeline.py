"""pipeline.py — main indexing pipeline.

Moved from ingest/pipeline.py with the following changes:
- Imports updated to graph.* and indexer.*
- Internal store calls converted:
  await async_fn(db, ...) → await asyncio.to_thread(repo.method, ...)
- Signature changed: index_repo(repo_path, *, repo: Repository, ...)
  instead of (repo_path, db: DB, ...)
- index_repo() stays async def — callers already use asyncio.run() or await
- Communities/coupling stay on old paths until Phase 3 (intelligence/) moves them
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import os
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
from loom.indexer.languages.constants import EXT_PY, EXT_PYW
from loom.indexer.registry import get_registry
from loom.indexer.utils import sha256_of_file
from loom.indexer.walker import walk_repo

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


def _read_import_lines(path: str) -> list[str]:
    """Read first 60 lines of a file and return lines that look like imports."""
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= 60:
                    break
                stripped = line.strip()
                if stripped.startswith(("import ", "from ", "require(", "#include", "using ")):
                    lines.append(stripped)
            return lines
    except OSError:
        return []


def _file_merge(
    repo: Repository,
    rel_path: str,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Delete old nodes/edges/tags for a path, then insert new nodes+edges.

    Differs from nodes.upsert: hard-deletes old nodes (matching current upsert behavior)
    and also hard-deletes system tags. Agent summaries for re-appearing node IDs are
    preserved.
    """
    now = int(time.time())

    node_rows = [
        (
            n.id,
            n.kind.value,
            n.source.value,
            n.name,
            n.path,
            n.start_line,
            n.end_line,
            n.language,
            n.content_hash,
            n.file_hash,
            n.file_mtime,
            n.summary,
            # token_count
            (
                max(1, n.end_line - n.start_line + 1) * 15
                if n.start_line is not None
                and n.end_line is not None
                and n.kind.value not in ("file", "community")
                else None
            ),
            n.community_id,
            n.complexity.value if n.complexity is not None else None,
            json.dumps(n.metadata, default=str) if n.metadata else "{}",
            n.language_notes,
            now,
        )
        for n in nodes
    ]
    edge_rows = [
        (
            e.from_id,
            e.to_id,
            e.kind.value,
            e.confidence,
            e.confidence_tier.value,
            json.dumps(e.metadata, default=str) if e.metadata else "{}",
        )
        for e in edges
    ]

    with repo.db._lock:
        conn = repo.db.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Save agent summaries for nodes that survive re-parse
            saved: dict[str, tuple[str | None, str | None]] = {
                r["id"]: (r["summary"], r["summary_hash"])
                for r in conn.execute(
                    "SELECT id, summary, summary_hash FROM nodes "
                    "WHERE path = ? AND summary IS NOT NULL",
                    (rel_path,),
                ).fetchall()
            }

            # Collect old node IDs (for tag cleanup before deleting nodes)
            old_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM nodes WHERE path = ?",
                    (rel_path,),
                ).fetchall()
            ]

            if old_ids:
                placeholders = ",".join("?" * len(old_ids))
                # Only delete OUTGOING edges from re-indexed nodes
                # Incoming cross-file edges are preserved (unchanged files won't be re-parsed)
                conn.execute(
                    f"DELETE FROM edges WHERE from_id IN ({placeholders})",
                    old_ids,
                )
                # Hard-delete system tags for old nodes
                conn.execute(
                    "DELETE FROM node_tags WHERE node_id IN "
                    f"({placeholders}) AND source = 'system'",
                    old_ids,
                )

            # Hard-delete old nodes for this path
            conn.execute("DELETE FROM nodes WHERE path = ?", (rel_path,))

            # Insert new nodes
            if node_rows:
                conn.executemany(
                    """INSERT OR IGNORE INTO nodes
                         (id, kind, source, name, path, start_line, end_line,
                          language, content_hash, file_hash, file_mtime, summary,
                          token_count, community_id, complexity, metadata, language_notes,
                          updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    node_rows,
                )

            # Insert new edges
            if edge_rows:
                conn.executemany(
                    """INSERT OR REPLACE INTO edges
                         (from_id, to_id, kind, confidence, confidence_tier, metadata)
                       VALUES (?,?,?,?,?,?)""",
                    edge_rows,
                )

            # Restore agent summaries for surviving node IDs
            new_node_ids = {n.id for n in nodes}
            for node_id, (summary, summary_hash) in saved.items():
                if summary and node_id in new_node_ids:
                    conn.execute(
                        "UPDATE nodes SET summary = ?, summary_hash = ? "
                        "WHERE id = ? AND summary IS NULL",
                        (summary, summary_hash, node_id),
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise


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

    # Inject repo_name into the environment so worker processes inherit it.
    # This enables 4-part node IDs (kind:repo:path:symbol) in all parsers.
    repo_name = await asyncio.to_thread(repo.db.get_repo_name)
    _prev_repo_name = os.environ.get("LOOM_REPO_NAME")
    os.environ["LOOM_REPO_NAME"] = repo_name
    logger.info("[init] repo_name=%r (injected into LOOM_REPO_NAME)", repo_name)

    def _emit(phase: str, done: int, total: int) -> None:
        if progress_cb is not None:
            with contextlib.suppress(Exception):
                progress_cb(phase, done, total)

    # --- Phase 1: discover files ---
    logger.info("[scan] discovering files in %s (workers=%d)", repo_path, max_workers)
    t = time.perf_counter()
    files_by_lang = walk_repo(str(repo_path))
    all_files_str: list[str] = [fp for fps in files_by_lang.values() for fp in fps]
    all_files: list[Path] = [Path(fp) for fp in all_files_str]

    # --- Phase 2: classify changes with IncrementalSync ---
    from loom.indexer.incremental import ChangeReport, IncrementalSync  # noqa: PLC0415

    sync = IncrementalSync(repo)
    report: ChangeReport = await asyncio.to_thread(sync.classify_changes, all_files_str)
    changed: list[Path] = [Path(p) for p in report.files_to_index]
    skipped: int = len(report.unchanged) + len(report.mtime_only)

    # Update mtime-only fingerprints (content unchanged, just mtime differs)
    if report.mtime_only:

        def _update_mtimes() -> None:
            for p in report.mtime_only:
                try:
                    mtime_ns = Path(p).stat().st_mtime_ns
                    repo.fingerprints.update_mtime(p, mtime_ns)
                except OSError:
                    pass

        await asyncio.to_thread(_update_mtimes)

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

    # --- Phase 3: parse ---
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

    # --- Phase 4: resolve cross-file calls ---
    if nodes_all:
        logger.info("[calls] resolving cross-file call edges")
        t = time.perf_counter()
        nodes_all, edges_all = resolve_calls(nodes_all, edges_all, repo_path)
        elapsed = time.perf_counter() - t
        logger.info("[calls] done in %.1fs — %d total edges", elapsed, len(edges_all))

    # --- Phase 5: write to DB ---
    by_path: dict[str, tuple[list[Node], list[Edge]]] = {}
    for n in nodes_all:
        if n.path not in by_path:
            by_path[n.path] = ([], [])
        by_path[n.path][0].append(n)

    # Build id→path lookup for routing — handles both 3-part and 4-part IDs
    _id_to_path: dict[str, str] = {n.id: n.path for n in nodes_all if n.path}

    for e in edges_all:
        src_path = _id_to_path.get(e.from_id, "")
        if not src_path:
            # Fallback: parse from ID format
            if e.from_id.startswith("file:"):
                src_path = e.from_id[5:]
            elif e.from_id.count(":") == 2:
                src_path = e.from_id.split(":", 2)[1]  # 3-part: kind:path:symbol
            elif e.from_id.count(":") >= 3:
                src_path = e.from_id.split(":", 3)[2]  # 4-part: kind:repo:path:symbol
        if src_path in by_path:
            by_path[src_path][1].append(e)

    if by_path:
        logger.info("[write] writing %d paths to DB", len(by_path))
        t = time.perf_counter()
        for path, (fn, fe) in by_path.items():
            await asyncio.to_thread(_file_merge, repo, path, fn, fe)
        logger.info("[write] done in %.1fs", time.perf_counter() - t)
    _emit("write", len(by_path), len(by_path))

    # Update fingerprints for indexed files
    if changed:
        from loom.graph.repository.fingerprints import FileFingerprint  # noqa: PLC0415

        fingerprints_to_write = []
        for f in changed:
            try:
                st = f.stat()
                rel = f.relative_to(repo_path).as_posix()
                file_nodes_for_path = by_path.get(rel, ([], []))[0]
                file_node = next((n for n in file_nodes_for_path if n.kind == NodeKind.FILE), None)
                content_sha = (
                    file_node.file_hash if file_node and file_node.file_hash else sha256_of_file(f)
                )
                fingerprints_to_write.append(
                    FileFingerprint(
                        file_path=f.as_posix(),
                        content_sha=content_sha,
                        mtime_ns=st.st_mtime_ns,
                        indexed_at=time.time(),
                    )
                )
            except OSError:
                pass
        if fingerprints_to_write:
            await asyncio.to_thread(repo.fingerprints.upsert, fingerprints_to_write)

    if not changed:
        logger.info("[skip] no files changed — skipping analysis phases")
    else:
        # --- Phase 5b: communities (still on old path until Phase 3) ---
        logger.info("[communities] computing Louvain communities")
        t = time.perf_counter()
        try:
            from loom.intelligence.communities import compute_communities  # noqa: PLC0415

            await compute_communities(repo.db)
            logger.info("[communities] done in %.1fs", time.perf_counter() - t)
        except Exception as exc:
            logger.warning("[communities] failed in %.1fs: %s", time.perf_counter() - t, exc)
        _emit("communities", 1, 1)

        # --- Phase 5c: coupling ---
        logger.info("[coupling] computing git co-change coupling")
        t = time.perf_counter()
        try:
            from loom.intelligence.coupling import compute_coupling  # noqa: PLC0415

            await compute_coupling(repo.db, repo_path)
            logger.info("[coupling] done in %.1fs", time.perf_counter() - t)
        except Exception as exc:
            logger.warning("[coupling] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 6: AutoTagger ---
        logger.info("[tagger] applying auto-tags to %d files", len(by_path))
        t = time.perf_counter()
        try:
            from loom.indexer.tagger import AutoTagger  # noqa: PLC0415

            tagger = AutoTagger()

            def _run_tagger() -> int:
                count = 0
                for path, (fn, _) in by_path.items():
                    imports = _read_import_lines(str(repo_path / path))
                    tag_result = tagger.tag_file(fn, imports, path)
                    for node_id, tags in tag_result.items():
                        if tags:
                            repo.tags.add_tags(node_id, tags, source="system")
                            count += len(tags)
                return count

            tag_count = await asyncio.to_thread(_run_tagger)
            logger.info(
                "[tagger] done in %.1fs — %d tags applied", time.perf_counter() - t, tag_count
            )
        except Exception as exc:
            logger.warning("[tagger] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 7: auto-summaries ---
        logger.info("[summaries] generating auto-summaries for unsummarized nodes")
        t = time.perf_counter()
        try:
            filled = await _fill_auto_summaries(repo)
            elapsed = time.perf_counter() - t
            logger.info("[summaries] done in %.1fs — %d summaries written", elapsed, filled)
        except Exception as exc:
            logger.warning("[summaries] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 10: TestLinker — TESTED_BY edges ---
        logger.info("[test_linker] linking test nodes to production nodes")
        t = time.perf_counter()
        try:
            from loom.indexer.test_linker import TestLinker  # noqa: PLC0415

            def _run_test_linker() -> tuple[int, int]:
                # Get all non-deleted function/method nodes for link_all
                with repo.db._lock:
                    conn = repo.db.connect()
                    rows = conn.execute(
                        "SELECT id, kind, name, path, language, source, content_hash, "
                        "start_line, end_line FROM nodes "
                        "WHERE kind IN ('function','method','class') AND deleted_at IS NULL"
                    ).fetchall()
                nodes_for_linking = []
                for r in rows:
                    try:
                        nodes_for_linking.append(
                            Node(
                                id=r["id"],
                                kind=NodeKind(r["kind"]),
                                source=NodeSource(r["source"]),
                                name=r["name"],
                                path=r["path"],
                                language=r["language"],
                                content_hash=r["content_hash"],
                                start_line=r["start_line"],
                                end_line=r["end_line"],
                            )
                        )
                    except Exception:
                        continue
                linker = TestLinker(repo)
                test_edges, test_tags = linker.link_all(nodes_for_linking)
                repo.edges.upsert(test_edges)
                for node_id, tags in test_tags.items():
                    if tags:
                        repo.tags.add_tags(node_id, tags, source="system")
                return len(test_edges), sum(len(v) for v in test_tags.values())

            edge_count, tag_count = await asyncio.to_thread(_run_test_linker)
            logger.info(
                "[test_linker] done in %.1fs — %d TESTED_BY edges, %d tags",
                time.perf_counter() - t,
                edge_count,
                tag_count,
            )
        except Exception as exc:
            logger.warning("[test_linker] failed in %.1fs: %s", time.perf_counter() - t, exc)

        # --- Phase 11: GraphTagger — dead-code, entry-point, hub, bridge ---
        logger.info("[graph_tagger] computing graph-derived tags")
        t = time.perf_counter()
        try:
            from loom.indexer.graph_tagger import compute_graph_tags  # noqa: PLC0415

            def _run_graph_tagger() -> int:
                graph_tags = compute_graph_tags(repo)
                count = 0
                for node_id, tags in graph_tags.items():
                    if tags:
                        repo.tags.add_tags(node_id, tags, source="system")
                        count += len(tags)
                return count

            gtag_count = await asyncio.to_thread(_run_graph_tagger)
            logger.info(
                "[graph_tagger] done in %.1fs — %d tags", time.perf_counter() - t, gtag_count
            )
        except Exception as exc:
            logger.warning("[graph_tagger] failed in %.1fs: %s", time.perf_counter() - t, exc)

    # --- Phase 12b: EdgeDescriber sweep ---
    try:
        from loom.indexer.edge_describer import describe_edges  # noqa: PLC0415

        def _run_describer() -> int:
            all_nodes = repo.nodes.list_all_undeleted()
            nodes_by_id = {n.id: n for n in all_nodes}
            all_edges = repo.edges.get_all()
            count = describe_edges(all_edges, nodes_by_id)
            if count:
                with repo.db._lock:
                    conn = repo.db.connect()
                    for e in all_edges:
                        if e.description:
                            conn.execute(
                                "UPDATE edges SET description = ? "
                                "WHERE from_id = ? AND to_id = ? AND kind = ?",
                                (
                                    e.description,
                                    e.from_id,
                                    e.to_id,
                                    e.kind.value if hasattr(e.kind, "value") else str(e.kind),
                                ),
                            )
                    conn.commit()
            return count

        t = time.perf_counter()
        n = await asyncio.to_thread(_run_describer)
        logger.info("[edge_describer] %d edges described in %.1fs", n, time.perf_counter() - t)
    except Exception as exc:
        logger.warning("[edge_describer] failed: %s", exc)

    # --- Phase 12c: Architecture layer assignment ---
    try:
        from loom.intelligence.architecture import assign_and_store_layers  # noqa: PLC0415

        def _run_arch() -> dict:
            return assign_and_store_layers(repo, repo_path)

        t = time.perf_counter()
        layer_counts = await asyncio.to_thread(_run_arch)
        logger.info(
            "[architecture] %d nodes layered in %.1fs — %s",
            sum(layer_counts.values()),
            time.perf_counter() - t,
            layer_counts,
        )
    except Exception as exc:
        logger.warning("[architecture] failed: %s", exc)

    # --- Phase 12: soft-delete removed files ---
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

        # After soft-deleting nodes, also delete fingerprints for removed files
        deleted_abs = [
            (repo_path / ip).as_posix() for ip in indexed_paths if ip not in current_rel_paths
        ]
        if deleted_abs:
            await asyncio.to_thread(repo.fingerprints.delete_paths, deleted_abs)

        await asyncio.to_thread(repo.nodes.prune_tombstones)
    except Exception as exc:
        logger.warning("[cleanup] deleted_file_detection failed: %s", exc)

    # --- Phase 13: prune sessions ---
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

    # Restore LOOM_REPO_NAME to its prior state (important for test isolation).
    if _prev_repo_name is None:
        os.environ.pop("LOOM_REPO_NAME", None)
    else:
        os.environ["LOOM_REPO_NAME"] = _prev_repo_name

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
