from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

from loom.analysis.code.parser import parse_code
from loom.core.edge import Edge, EdgeType
from loom.core.graph import LoomGraph
from loom.core.node import Node, NodeKind, NodeSource
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo
from loom.ingest.utils import sha256_of_file

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
    """Remap a node ID from absolute path to POSIX-relative path form."""
    # Symbol-bearing nodes: "kind:{abs_path}:{symbol}"
    if f":{abs_path}:" in old_id:
        return old_id.replace(f":{abs_path}:", f":{rel_path}:", 1)
    # FILE nodes: "file:{abs_path}" (no trailing colon)
    if old_id.endswith(f":{abs_path}"):
        return old_id[: -len(abs_path)] + rel_path
    return old_id


def _get_call_tracer(abs_path: str):  # type: ignore[return]
    handler = get_registry().get_handler_for_path(abs_path)
    if handler is None:
        return None
    return handler.call_tracer


def _parse_file(file_path: Path, *, repo_root: Path) -> ParseResult:
    """Parse a single file. Returns nodes/edges/errors.

    Every returned Node has:
      - path = POSIX repo-relative (no leading ./)
      - file_hash = sha256_of_file(file_path)
      - id built with the same rel path
      - content_hash = sha256 of symbol's source slice (set by parser)

    Every returned Edge uses from_id/to_id matching those node IDs.
    Paths are never absolute and never use backslashes.
    """
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

    # Build abs→rel ID mapping
    id_map: dict[str, str] = {}
    for n in raw_nodes:
        new_id = _remap_id(n.id, abs_path, rel_path)
        id_map[n.id] = new_id

    # Add FILE node (parsers may or may not emit one)
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

    # Remap parsed nodes
    nodes: list[Node] = [file_node]
    for n in raw_nodes:
        if n.kind == NodeKind.FILE:
            continue  # already added our canonical FILE node above
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

    # Per-file call tracing (uses abs path to read source)
    tracer = _get_call_tracer(abs_path)
    raw_edges: list[Edge] = []
    if tracer is not None:
        try:
            raw_edges = tracer(abs_path, raw_nodes)
        except Exception as exc:
            logger.warning("call tracer failed for %s: %s", rel_path, exc)

    # CONTAINS edges: file → every non-file node
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

    # Remap call edges
    edges: list[Edge] = list(contains_edges)
    for e in raw_edges:
        new_from = id_map.get(e.from_id, _remap_id(e.from_id, abs_path, rel_path))
        new_to = id_map.get(e.to_id, e.to_id)  # keep unresolved: IDs as-is
        edges.append(e.model_copy(update={"from_id": new_from, "to_id": new_to}))

    return ParseResult(nodes=nodes, edges=edges)


def resolve_calls(
    nodes: list[Node], edges: list[Edge], repo_root: Path
) -> tuple[list[Node], list[Edge]]:
    """Enhance cross-file CALLS resolution for Python using a global symbol map."""
    from loom.analysis.code.calls.python import (
        _build_symbol_map,
        trace_calls_for_file_with_global_symbols,
    )
    from loom.ingest.code.languages.constants import EXT_PY, EXT_PYW

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
    graph: LoomGraph,
    *,
    workers: int | None = None,
) -> IndexResult:
    """Index a repo into the graph.

    Walk, parse (parallel), cross-file call resolution, per-file atomic replace,
    then community detection and dead-code marking.
    """
    repo_path = repo_path.resolve()

    files_by_lang = walk_repo(str(repo_path))
    all_files: list[Path] = [
        Path(fp) for fps in files_by_lang.values() for fp in fps
    ]

    existing = await graph.get_content_hashes()
    changed: list[Path] = []
    skipped = 0
    for f in all_files:
        rel = f.relative_to(repo_path).as_posix()
        if sha256_of_file(f) == existing.get(rel):
            skipped += 1
        else:
            changed.append(f)

    logger.info(
        "index_repo root=%s total=%d changed=%d skipped=%d",
        repo_path,
        len(all_files),
        len(changed),
        skipped,
    )

    nodes_all: list[Node] = []
    edges_all: list[Edge] = []
    errors: list[str] = []

    max_workers = workers or min(cpu_count(), 8)

    if len(changed) >= 8:
        # Parallel parse via ProcessPoolExecutor
        import functools

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

    # Cross-file call resolution (Python only)
    nodes_all, edges_all = resolve_calls(nodes_all, edges_all, repo_path)

    # Group per-file and atomically replace
    by_path: dict[str, tuple[list[Node], list[Edge]]] = {}
    for n in nodes_all:
        if n.path not in by_path:
            by_path[n.path] = ([], [])
        by_path[n.path][0].append(n)

    for e in edges_all:
        # Assign edge to the path of its source node
        src_path = ""
        if e.from_id.count(":") >= 2:
            src_path = e.from_id.split(":", 2)[1]
        elif e.from_id.startswith("file:"):
            src_path = e.from_id[5:]
        if src_path in by_path:
            by_path[src_path][1].append(e)

    for path, (fn, fe) in by_path.items():
        await graph.replace_file(path, fn, fe)

    # Post-processing analysis
    try:
        from loom.analysis.communities import (
            compute_communities,  # type: ignore[import]
        )

        await compute_communities(graph)
    except ImportError:
        logger.debug("compute_communities not available yet")
    except Exception as exc:
        logger.warning("compute_communities failed: %s", exc)

    try:
        from loom.analysis.coupling import compute_coupling  # type: ignore[import]

        await compute_coupling(graph, repo_path)
    except ImportError:
        logger.debug("compute_coupling not available yet")
    except Exception as exc:
        logger.warning("compute_coupling failed: %s", exc)

    try:
        from loom.analysis.dead_code import mark_dead_code  # type: ignore[import]

        await mark_dead_code(graph)
    except ImportError:
        logger.debug("mark_dead_code not available yet")
    except Exception as exc:
        logger.warning("mark_dead_code failed: %s", exc)

    return IndexResult(
        repo_path=repo_path,
        files_parsed=len(changed),
        files_skipped=skipped,
        nodes_written=len(nodes_all),
        edges_written=len(edges_all),
        errors=errors,
    )
