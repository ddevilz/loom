from __future__ import annotations

import os
from pathlib import Path

from pathspec import PathSpec

from loom.config import DEFAULT_SKIP_DIRS
from loom.ingest.code.registry import get_registry


def _load_gitignore(root: Path) -> PathSpec:
    gi = root / ".gitignore"
    if not gi.exists():
        return PathSpec.from_lines("gitignore", [])

    lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
    return PathSpec.from_lines("gitignore", lines)


def _is_hidden_dir(name: str) -> bool:
    return name.startswith(".")


def _should_skip_dir(name: str, *, skip_dirs: frozenset[str]) -> bool:
    if name in skip_dirs:
        return True
    return bool(_is_hidden_dir(name))


def _to_posix_rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


def _to_posix_abs(p: Path) -> str:
    return p.resolve().as_posix()


def walk_repo(
    path: str,
    *,
    skip_dirs: frozenset[str] = DEFAULT_SKIP_DIRS,
) -> dict[str, list[str]]:
    """Walk a repo and return file paths grouped by language.

    - Respects .gitignore (root-level) using pathspec gitwildmatch
    - Skips DEFAULT_SKIP_DIRS, hidden dirs, and symlinked directories
    - Detects language by file extension

    Paths returned are absolute paths.
    """

    root = Path(path).resolve()
    spec = _load_gitignore(root)
    registry = get_registry()

    results: dict[str, list[str]] = {}

    stack: list[Path] = [root]

    while stack:
        cur = stack.pop()

        with os.scandir(cur) as it:
            for entry in it:
                name = entry.name
                entry_path = Path(entry.path)

                if entry.is_dir(follow_symlinks=False):
                    if entry.is_symlink():
                        continue

                    if _should_skip_dir(name, skip_dirs=skip_dirs):
                        continue

                    rel = _to_posix_rel(root, entry_path)
                    if spec.match_file(rel + "/"):
                        continue

                    stack.append(entry_path)
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                rel = _to_posix_rel(root, entry_path)
                if spec.match_file(rel):
                    continue

                if registry.should_skip_path(str(entry_path)):
                    continue

                lang = registry.get_language_for_path(str(entry_path))
                if lang is None:
                    continue

                results.setdefault(lang, []).append(_to_posix_abs(entry_path))

    for files in results.values():
        files.sort()

    return results
