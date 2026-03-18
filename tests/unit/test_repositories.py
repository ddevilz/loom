from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def test_repositories_igraph_import_is_lazy() -> None:
    """igraph must only be imported inside _rank_by_personalized_pagerank, not at module level."""
    spec = importlib.util.find_spec("loom.core.falkor.repositories")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)

    # Only check top-level statements in the module body
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and "igraph" in node.module:
            assert False, (
                f"igraph imported at module level (line {node.lineno}). "
                "Move it inside _rank_by_personalized_pagerank."
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "igraph" in alias.name:
                    assert False, (
                        f"igraph imported at module level (line {node.lineno}). "
                        "Move it inside _rank_by_personalized_pagerank."
                    )
