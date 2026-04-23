from __future__ import annotations

import functools
import logging
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path

from loom.core.context import DB
from loom.ingest.code.walker import walk_repo
from loom.ingest.pipeline import _parse_file, resolve_calls
from loom.ingest.utils import sha256_of_file
from loom.store import nodes as node_store

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
    )
    return [repo / line.strip() for line in out.splitlines() if line.strip()]


async def sync_paths(
    db: DB,
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
        stored = await node_store.get_file_hash(db, rel)
        if sha256_of_file(f) != stored:
            changed.append(f)

    if not changed:
        return SyncResult(0, 0, 0)

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
        await node_store.replace_file(db, path, fn, fe)

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
    )
