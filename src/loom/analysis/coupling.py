from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path

import git

from loom.core.context import DB
from loom.core.edge import Edge, EdgeType
from loom.store import edges as edge_store

logger = logging.getLogger(__name__)

_GIT_SINCE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_FILES_PER_COMMIT = 50
_DEFAULT_MONTHS = 6
_DEFAULT_THRESHOLD = 0.3
_META_KEY = "coupling_last_commit_ts"


def _file_node_id(rel_path: str) -> str:
    return f"file:{rel_path}"


def _get_meta(db: DB, key: str) -> str | None:
    with db._lock:
        row = db.connect().execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def _set_meta(db: DB, key: str, value: str) -> None:
    with db._lock:
        conn = db.connect()
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


async def compute_coupling(
    db: DB,
    repo_path: Path,
    *,
    months: int = _DEFAULT_MONTHS,
    threshold: float = _DEFAULT_THRESHOLD,
) -> int:
    """Analyze git history to find co-changing files; persist COUPLED_WITH edges.

    Skips re-analysis if the newest commit hasn't changed since the last run.
    Returns count of coupling edges written.
    """
    try:
        repo = await asyncio.to_thread(
            git.Repo, str(repo_path), search_parent_directories=True
        )
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as exc:
        logger.warning("Not a valid git repo %s: %s", repo_path, exc)
        return 0

    def _latest_commit_ts() -> str | None:
        try:
            commit = next(repo.iter_commits(max_count=1))
            return str(commit.committed_date)
        except (StopIteration, git.GitCommandError):
            return None

    latest_ts = await asyncio.to_thread(_latest_commit_ts)
    if latest_ts is None:
        return 0

    stored_ts = await asyncio.to_thread(_get_meta, db, _META_KEY)
    if stored_ts == latest_ts:
        logger.info("[coupling] no new commits since last run — skipped")
        return 0

    edges = await _analyze_coupling(repo, repo_path, months=months, threshold=threshold)
    if edges:
        await edge_store.bulk_upsert_edges(db, edges)
    await asyncio.to_thread(_set_meta, db, _META_KEY, latest_ts)
    return len(edges)


async def _analyze_coupling(
    repo: git.Repo,
    repo_path: Path,
    *,
    months: int,
    threshold: float,
) -> list[Edge]:
    """Return COUPLED_WITH edges from git co-change history."""
    working_dir = repo.working_tree_dir
    if not isinstance(working_dir, str) or not working_dir:
        logger.warning("No working tree for %s", repo_path)
        return []
    root = Path(working_dir)

    cutoff = datetime.now(UTC) - timedelta(days=months * 30)

    def _process() -> list[Edge]:
        try:
            commits = list(
                repo.iter_commits(since=cutoff.strftime(_GIT_SINCE_FORMAT))
            )
        except git.GitCommandError as exc:
            logger.warning("git iter_commits failed: %s", exc)
            return []

        if not commits:
            return []

        file_sets: list[set[str]] = []
        appearances: dict[str, int] = defaultdict(int)

        for commit in commits:
            changed: set[str] = set()
            if commit.parents:
                for parent in commit.parents:
                    try:
                        for diff in commit.diff(parent):
                            if diff.a_path:
                                changed.add(diff.a_path)
                            if diff.b_path and diff.b_path != diff.a_path:
                                changed.add(diff.b_path)
                    except Exception:
                        pass
            else:
                try:
                    for item in commit.tree.traverse():
                        if item.type == "blob":  # type: ignore[union-attr]
                            changed.add(item.path)  # type: ignore[union-attr]
                except Exception:
                    continue

            if len(changed) > _MAX_FILES_PER_COMMIT:
                continue
            if changed:
                file_sets.append(changed)
                for fp in changed:
                    appearances[fp] += 1

        if not file_sets:
            return []

        pair_count: dict[tuple[str, str], int] = defaultdict(int)
        for changed in file_sets:
            for a, b in combinations(sorted(changed), 2):
                pair_count[(a, b)] += 1

        edges: list[Edge] = []
        for (a, b), count in pair_count.items():
            max_app = max(appearances[a], appearances[b])
            freq = count / max_app
            if freq < threshold:
                continue
            edges.append(
                Edge(
                    from_id=_file_node_id(a),
                    to_id=_file_node_id(b),
                    kind=EdgeType.COUPLED_WITH,
                    confidence=freq,
                    metadata={
                        "coupling_frequency": freq,
                        "cooccurrence_count": count,
                        "analysis_months": months,
                    },
                )
            )

        logger.info(
            "compute_coupling repo=%s edges=%d months=%d threshold=%s",
            root,
            len(edges),
            months,
            threshold,
        )
        return edges

    return await asyncio.to_thread(_process)
