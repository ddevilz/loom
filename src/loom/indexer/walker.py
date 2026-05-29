from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pathspec import PathSpec

from loom.config import DEFAULT_SKIP_DIRS
from loom.indexer.registry import get_registry


def _load_gitignore(root: Path) -> PathSpec:
    """Load .gitignore files from the repo (used by fallback walker only)."""
    lines: list[str] = []
    skip = DEFAULT_SKIP_DIRS | frozenset({"node_modules"})

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        if ".gitignore" not in filenames:
            continue
        gi = Path(dirpath) / ".gitignore"
        try:
            rel_dir = gi.parent.relative_to(root).as_posix()
            prefix = "" if rel_dir == "." else rel_dir + "/"
            for line in gi.read_text(encoding="utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    lines.append(line)
                    continue
                if not stripped.startswith("/") and prefix:
                    lines.append(prefix + stripped)
                else:
                    lines.append(line)
        except OSError:
            continue
    return PathSpec.from_lines("gitignore", lines)


def _should_skip_dir(name: str, *, skip_dirs: frozenset[str]) -> bool:
    return name in skip_dirs or name.startswith(".")


def _to_posix_rel(root: Path, p: Path) -> str:
    return str(p.relative_to(root)).replace("\\", "/")


def _git_ls_files(root: Path) -> list[str] | None:
    """Primary discovery: return project-relative POSIX paths via git ls-files.

    Uses -z -co --exclude-standard:
      -z : NUL-delimited (handles non-ASCII paths)
      -c : cached (tracked) files
      -o : untracked files not ignored
      --exclude-standard : honor .gitignore / .git/info/exclude

    Returns None if not a git repo (caller should fall back).
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "-co", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.split(b"\0")
        return [p.decode("utf-8", errors="replace") for p in raw if p]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def _walk_directory(root: Path, *, skip_dirs: frozenset[str]) -> list[str]:
    """Fallback discovery for non-git repos. Returns project-relative POSIX paths."""
    spec = _load_gitignore(root)
    files: list[str] = []
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
                elif entry.is_file(follow_symlinks=False):
                    rel = _to_posix_rel(root, entry_path)
                    if not spec.match_file(rel):
                        files.append(rel)
    return files


def walk_repo(
    path: str,
    *,
    skip_dirs: frozenset[str] = DEFAULT_SKIP_DIRS,
) -> dict[str, list[str]]:
    """Walk a repo and return file paths grouped by language.

    Primary: git ls-files (correct gitignore semantics, multi-module safe).
    Fallback: directory walker (non-git repos only).
    """
    root = Path(path).resolve()
    rel_paths = _git_ls_files(root)
    if rel_paths is None:
        rel_paths = _walk_directory(root, skip_dirs=skip_dirs)

    registry = get_registry()
    results: dict[str, list[str]] = {}

    for rel in rel_paths:
        abs_path = (root / rel).resolve()
        if not abs_path.is_file():
            continue
        if registry.should_skip_path(str(abs_path)):
            continue
        lang = registry.get_language_for_path(str(abs_path))
        if lang is None:
            continue
        results.setdefault(lang, []).append(abs_path.as_posix())

    for files in results.values():
        files.sort()
    return results
