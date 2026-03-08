from __future__ import annotations

import os
from pathlib import Path

from pathspec import PathSpec

from loom.config import DEFAULT_SKIP_DIRS
from loom.ingest.code.registry import get_registry
from loom.ingest.code.languages.constants import (
    EXT_CSS,
    EXT_CXML,
    EXT_ENV,
    EXT_GO,
    EXT_HTM,
    EXT_HTML,
    EXT_JAVA,
    EXT_JS,
    EXT_JSX,
    EXT_JSON,
    EXT_PROPERTIES,
    EXT_PY,
    EXT_PYW,
    EXT_RB,
    EXT_RS,
    EXT_TS,
    EXT_TSX,
    EXT_TOML,
    EXT_XML,
    EXT_YAML,
    EXT_YML,
    EXT_INI,
    LANG_CSS,
    LANG_ENV,
    LANG_GO,
    LANG_HTML,
    LANG_INI,
    LANG_JAVA,
    LANG_JAVASCRIPT,
    LANG_JSON,
    LANG_PYTHON,
    LANG_PROPERTIES,
    LANG_RUBY,
    LANG_RUST,
    LANG_TSX,
    LANG_TOML,
    LANG_TYPESCRIPT,
    LANG_XML,
    LANG_YAML,
)


_EXT_TO_LANGUAGE: dict[str, str] = {
    EXT_PY: LANG_PYTHON,
    EXT_PYW: LANG_PYTHON,
    EXT_TS: LANG_TYPESCRIPT,
    EXT_TSX: LANG_TSX,
    EXT_JS: LANG_JAVASCRIPT,
    EXT_JSX: LANG_JAVASCRIPT,
    EXT_GO: LANG_GO,
    EXT_JAVA: LANG_JAVA,
    EXT_RS: LANG_RUST,
    EXT_RB: LANG_RUBY,
    EXT_HTML: LANG_HTML,
    EXT_HTM: LANG_HTML,
    EXT_XML: LANG_XML,
    EXT_CXML: LANG_XML,
    EXT_JSON: LANG_JSON,
    EXT_CSS: LANG_CSS,
    EXT_YAML: LANG_YAML,
    EXT_YML: LANG_YAML,
    EXT_PROPERTIES: LANG_PROPERTIES,
    EXT_TOML: LANG_TOML,
    EXT_INI: LANG_INI,
}


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
    if _is_hidden_dir(name):
        return True
    return False


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

        try:
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

                    ext = registry.get_extension_for_path(str(entry_path))
                    if registry.should_skip_path(str(entry_path)):
                        continue

                    lang = LANG_ENV if ext == EXT_ENV else _EXT_TO_LANGUAGE.get(ext)
                    if lang is None:
                        continue

                    results.setdefault(lang, []).append(_to_posix_abs(entry_path))

        except (PermissionError, FileNotFoundError):
            continue

    for files in results.values():
        files.sort()

    return results
