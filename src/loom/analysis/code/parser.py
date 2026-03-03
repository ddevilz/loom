from __future__ import annotations

import logging
from pathlib import Path

from loom.core import Node
from loom.ingest.code.registry import get_registry

logger = logging.getLogger(__name__)


def parse_code(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Parse a single file into Nodes. Returns [] for unsupported extensions."""
    reg = get_registry()
    ext = Path(path).suffix.lower()

    if reg.should_skip_file(ext):
        return []

    parser = reg.get_parser(ext)
    if parser is None:
        return []

    return parser(path, exclude_tests=exclude_tests)


def parse_tree(
    root: str,
    *,
    exclude_tests: bool = False,
) -> list[Node]:
    """Walk a directory tree recursively and parse all supported files.

    Automatically skips:
    - Directories in SKIP_DIRS (.git, node_modules, __pycache__, .venv, ...)
    - Files with non-code extensions (.html, .css, .xml, .png, .pdf, ...)
    - Only parses files whose extension has a registered language parser
    """
    reg = get_registry()
    root_path = Path(root)

    if not root_path.is_dir():
        return parse_code(root, exclude_tests=exclude_tests)

    all_nodes: list[Node] = []
    file_count = 0
    skip_count = 0

    for item in sorted(root_path.rglob("*")):
        # skip ignored directories (check each parent component)
        if any(reg.should_skip_dir(part) for part in item.parts):
            continue

        if not item.is_file():
            continue

        ext = item.suffix.lower()
        if reg.should_skip_file(ext):
            skip_count += 1
            continue

        try:
            nodes = parse_code(str(item), exclude_tests=exclude_tests)
            all_nodes.extend(nodes)
            file_count += 1
        except Exception:
            logger.warning("Failed to parse %s", item, exc_info=True)

    logger.info(
        "parse_tree: %d files parsed, %d skipped, %d symbols extracted",
        file_count,
        skip_count,
        len(all_nodes),
    )
    return all_nodes
