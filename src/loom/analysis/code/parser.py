from __future__ import annotations

import logging
from pathlib import Path

from loom.core import Node
from loom.ingest.code.registry import get_registry
from loom.ingest.code.walker import walk_repo

logger = logging.getLogger(__name__)


def parse_code(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Parse a single file into Nodes. Returns [] for unsupported extensions."""
    reg = get_registry()
    if reg.should_skip_path(path):
        return []

    handler = reg.get_handler_for_path(path)
    if handler is None:
        return []

    return handler.parser(path, exclude_tests=exclude_tests)


def parse_repo(
    root: str,
    *,
    exclude_tests: bool = False,
) -> list[Node]:
    """Parse an entire repo/directory into Nodes.

    Discovery is delegated to `walk_repo()` (gitignore-aware, symlink-safe).
    Parsing is delegated to `parse_code()`.
    """

    root_path = Path(root)
    if root_path.is_file():
        return parse_code(str(root_path), exclude_tests=exclude_tests)

    files_by_lang = walk_repo(str(root_path))
    all_files: list[str] = []
    for files in files_by_lang.values():
        all_files.extend(files)

    all_nodes: list[Node] = []
    file_count = 0
    for fp in sorted(all_files):
        try:
            all_nodes.extend(parse_code(fp, exclude_tests=exclude_tests))
            file_count += 1
        except Exception:
            logger.warning("Failed to parse %s", fp, exc_info=True)

    logger.info(
        "parse_repo: %d files parsed, %d symbols extracted", file_count, len(all_nodes)
    )
    return all_nodes
