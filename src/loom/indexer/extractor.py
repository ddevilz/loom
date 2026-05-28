"""extractor.py — merged from analysis/code/extractor.py + analysis/code/parser.py.

Provides:
    extract_summary(node) — static summary from metadata, no LLM
    extract_summaries(nodes) — batch version
    parse_code(path) — parse single file into Node list
    parse_repo(root) — parse entire repo into Node list
"""
from __future__ import annotations

import logging
from pathlib import Path

from loom.graph.models import Node, NodeKind

logger = logging.getLogger(__name__)


def extract_summary(node: Node) -> str:
    """Extract a structured text summary from a node using only static metadata.

    No LLM calls, no network requests.
    """
    if node.kind == NodeKind.FILE:
        return f"file: {node.name}\npath: {node.path}"

    lines: list[str] = []
    lines.append(f"{node.kind.value}: {node.name}")

    params = node.metadata.get("params")
    if isinstance(params, list) and params:
        lines.append(f"params: {', '.join(str(p) for p in params)}")
    elif params is not None and not isinstance(params, list):
        lines.append("params: none")

    return_type = node.metadata.get("return_type")
    if return_type:
        lines.append(f"returns: {return_type}")
    elif return_type is not None:
        lines.append("returns: unknown")

    raises = node.metadata.get("raises")
    if isinstance(raises, list) and raises:
        lines.append(f"raises: {', '.join(str(r) for r in raises)}")
    elif raises is not None and not isinstance(raises, list):
        lines.append("raises: none")

    calls = node.metadata.get("calls")
    if isinstance(calls, list) and calls:
        lines.append(f"calls: {', '.join(str(c) for c in calls)}")
    elif calls is not None and not isinstance(calls, list):
        lines.append("calls: none")

    lines.append(f"module: {node.path}")

    docstring = node.metadata.get("docstring")
    if isinstance(docstring, str) and docstring.strip():
        doc_text = docstring.strip()
        if len(doc_text) > 200:
            doc_text = doc_text[:200] + "..."
        lines.append(f"docstring: {doc_text}")

    return "\n".join(lines)


async def extract_summaries(nodes: list[Node]) -> list[Node]:
    """Assign static summaries to nodes that don't have one yet."""
    return [n if n.summary else n.model_copy(update={"summary": extract_summary(n)}) for n in nodes]


def parse_code(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Parse a single file into Nodes. Returns [] for unsupported extensions."""
    from loom.indexer.registry import get_registry

    reg = get_registry()
    if reg.should_skip_path(path):
        return []
    handler = reg.get_handler_for_path(path)
    if handler is None:
        return []
    return handler.parser(path, exclude_tests=exclude_tests)


def parse_repo(root: str, *, exclude_tests: bool = False) -> list[Node]:
    """Parse an entire repo/directory into Nodes."""
    from loom.indexer.walker import walk_repo

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

    logger.info("parse_repo: %d files parsed, %d symbols extracted", file_count, len(all_nodes))
    return all_nodes
