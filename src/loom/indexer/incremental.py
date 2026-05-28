"""incremental.py — sync changed files only.

Moved from ingest/incremental.py with imports updated to graph.* and indexer.*.
"""
from __future__ import annotations

import functools
import logging
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from pathlib import Path

from loom.graph.repository import Repository
from loom.indexer.pipeline import _parse_file, resolve_calls
from loom.indexer.utils import sha256_of_file
from loom.indexer.walker import walk_repo

logger = logging.getLogger(__name__)

_SAFE_REF = set("0123456789abcdefABCDEF~^/._-HEAD")


def _validate_ref(ref: str) -> None:
    if not ref or any(c not in _SAFE_REF for c in ref):
        raise ValueError(f"unsafe git ref: {ref!r}")


@dataclass
class SyncResult:
    files_changed: int
    nodes_written: int
    edges_written: int


def _git_diff_files(repo: Path, old: str, new: str) -> list[Path]:
    _validate_ref(old)
    _validate_ref(new)
    out = subprocess.check_output(
        ["git", "-C", str(repo), "diff", "--name-only", old, new],
        text=True,
    )
    return [repo / line.strip() for line in out.splitlines() if line.strip()]


async def sync_paths(
    repo: Repository,
    repo_path: Path,
    *,
    old_sha: str | None = None,
    new_sha: str | None = None,
) -> SyncResult:
    """Sync changed files into the graph.

    When old_sha and new_sha are provided, uses git diff to narrow the candidate
    set. Otherwise, walks the whole repo and filters by SHA-256 hash.
    """
    import asyncio

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
        stored = await asyncio.to_thread(repo.nodes.get_file_hash, rel)
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
        await asyncio.to_thread(repo.nodes.upsert, fn, fe, path)

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


@dataclass
class ChangeReport:
    new:        list[str] = field(default_factory=list)
    changed:    list[str] = field(default_factory=list)
    mtime_only: list[str] = field(default_factory=list)
    unchanged:  list[str] = field(default_factory=list)
    deleted:    list[str] = field(default_factory=list)

    @property
    def files_to_index(self) -> list[str]:
        """Files needing full parse — new + content-changed."""
        return self.new + self.changed

    @property
    def files_to_update_mtime(self) -> list[str]:
        """Files where only mtime changed — caller must update stored mtime to preserve fast-path."""
        return self.mtime_only


class IncrementalSync:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def classify_changes(self, discovered_files: list[str]) -> ChangeReport:
        """Three-tier change detection: mtime → SHA-256 → re-index.

        discovered_files: absolute paths returned by walk_repo().
        Handles TOCTOU race: files may vanish between walk and stat.
        """
        stored = self.repo.fingerprints.get_all()
        report = ChangeReport()
        discovered_set = set(discovered_files)

        for path in discovered_files:
            try:
                stat_result = os.stat(path)
            except FileNotFoundError:
                report.deleted.append(path)
                continue
            mtime_ns = stat_result.st_mtime_ns
            if path not in stored:
                report.new.append(path)
                continue
            fp = stored[path]
            if fp.mtime_ns == mtime_ns:
                report.unchanged.append(path)
                continue
            try:
                content_sha = sha256_of_file(Path(path))
            except FileNotFoundError:
                report.deleted.append(path)
                continue
            if fp.content_sha == content_sha:
                report.mtime_only.append(path)
                continue
            report.changed.append(path)

        report.deleted.extend([p for p in stored if p not in discovered_set])
        return report
