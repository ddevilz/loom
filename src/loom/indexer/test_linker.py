"""TestLinker — post-parse pass that creates TESTED_BY edges.

This module is pure computation: it takes already-parsed nodes and returns
(edges, tags) without touching the database.  The pipeline is responsible for
persisting the result via repo.edges.upsert() and repo.tags.add_tags().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.graph.models import Node
    from loom.graph.repository import Repository

# ---- Pattern configuration ----


@dataclass
class TestPattern:
    file_re: str | None = None
    dir_re: str | None = None
    strip_prefix: str | None = None
    strip_suffix: str | None = None
    mirror_src: str | None = None
    dir_swap: tuple[str, str] | None = None


TEST_PATTERNS: dict[str, list[TestPattern]] = {
    "python": [
        TestPattern(file_re=r"test_(.+)\.py$", strip_prefix="test_"),
        TestPattern(file_re=r"(.+)_test\.py$", strip_suffix="_test"),
        TestPattern(dir_re=r"tests?/", mirror_src="src/"),
    ],
    "typescript": [
        TestPattern(file_re=r"(.+)\.(test|spec)\.(ts|tsx)$"),
        TestPattern(dir_re=r"__tests__/"),
    ],
    "javascript": [
        TestPattern(file_re=r"(.+)\.(test|spec)\.(js|jsx)$"),
        TestPattern(dir_re=r"__tests__/"),
    ],
    "java": [
        TestPattern(dir_swap=("src/test/java", "src/main/java")),
        TestPattern(file_re=r"(.+)(Test|Tests|IT|Spec)\.java$"),
    ],
}

STRIP_RULES: dict[str, list[tuple[str, str]]] = {
    "python": [("test_", "prefix"), ("_test", "suffix")],
    "typescript": [("test", "prefix_camel")],
    "javascript": [("test", "prefix_camel")],
    "java": [
        ("Test", "prefix_camel"),
        ("Test", "suffix"),
        ("Tests", "suffix"),
        ("IT", "suffix"),
        ("Spec", "suffix"),
    ],
}

MIN_CONFIDENCE = 0.55  # HIGH tier — minimum 2 signals
MEDIUM_MIN_CONFIDENCE = 0.30  # MEDIUM tier — single strong signal (e.g. CALLS edge alone)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def is_test_file(path: str, language: str) -> bool:
    """Return True if this path matches any test pattern for the language."""
    patterns = TEST_PATTERNS.get(language, [])
    for p in patterns:
        if p.file_re and re.search(p.file_re, path):
            return True
        if p.dir_re and re.search(p.dir_re, path):
            return True
        if p.dir_swap and p.dir_swap[0] in path:
            return True
    return False


def strip_test_name(name: str, language: str) -> str:
    """Strip test prefix/suffix from a function or class name.

    strip types:
    - "prefix": remove exact leading string, case-sensitive
    - "suffix": remove exact trailing string, case-sensitive
    - "prefix_camel": remove case-insensitively from start and capitalize next char
    """
    rules = STRIP_RULES.get(language, [])
    for pattern, rule_type in rules:
        if rule_type == "prefix" and name.startswith(pattern):
            return name[len(pattern) :]
        elif rule_type == "suffix" and name.endswith(pattern):
            return name[: -len(pattern)]
        elif rule_type == "prefix_camel":
            lower_name = name.lower()
            lower_pat = pattern.lower()
            if lower_name.startswith(lower_pat):
                stripped = name[len(pattern) :]
                if stripped:
                    return stripped[0].upper() + stripped[1:]
                return stripped
    return name


def path_convention_match(test_path: str, prod_path: str, language: str) -> bool:
    """Return True if test_path and prod_path are convention-linked."""
    patterns = TEST_PATTERNS.get(language, [])
    for p in patterns:
        if p.file_re:
            m = re.search(p.file_re, test_path)
            if m:
                # Compare exact stem: captured group must equal prod_path's stem
                base = m.group(1)
                prod_stem = Path(prod_path).stem
                if base == prod_stem:
                    return True
        if p.dir_swap:
            test_dir, prod_dir = p.dir_swap
            if test_dir in test_path and prod_dir in prod_path:
                # Compare stems: TestFoo.java matches Foo.java
                return True
        if (
            p.dir_re
            and p.mirror_src
            and re.search(p.dir_re, test_path)
            and p.mirror_src in prod_path
        ):
            # Also require matching stems
            test_stem = re.sub(r"^test_|_test$", "", Path(test_path).stem)
            prod_stem = Path(prod_path).stem
            if test_stem == prod_stem:
                return True
    return False


def _read_test_content(path: str) -> str:
    """Read first 50 lines of test file for import analysis caching."""
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as f:
            return "".join(line for i, line in enumerate(f) if i < 50)
    except OSError:
        return ""


def _check_import(test_content: str, prod_path: str) -> bool:
    """Check if prod_path's module name appears in pre-loaded test file content."""
    prod_module = Path(prod_path).stem
    if not prod_module:
        return False
    return prod_module in test_content


def imports_module(test_path: str, prod_path: str) -> bool:
    """Public API — reads test file and checks for prod module import.

    This is a heuristic: reads test file and checks if prod module name appears as an import.
    For performance, we check by reading the first 50 lines only.
    Falls back to False if file can't be read.
    """
    return _check_import(_read_test_content(test_path), prod_path)


def name_match(stripped: str, prod_name: str) -> bool:
    """Return True if stripped test name matches production name (case-insensitive)."""
    return stripped.lower() == prod_name.lower()


def _has_direct_call_edge(test_node_id: str, prod_node_id: str, repo) -> bool:
    """Return True if a CALLS edge exists from test_node to prod_node in the graph."""
    if repo is None:
        return False
    from loom.graph.models.edge import EdgeType

    return repo.edges.edge_exists(test_node_id, prod_node_id, EdgeType.CALLS)


def match_test_to_production(
    test_node,
    prod_nodes: list,
    repo,
) -> list[tuple]:
    """Score test_node against each prod_node and return (prod, score, tier) triples.

    Tiers: 'HIGH' (score >= MIN_CONFIDENCE) or 'MEDIUM' (score >= MEDIUM_MIN_CONFIDENCE).
    """
    lang = test_node.language or ""
    path = test_node.path or ""
    stripped = strip_test_name(test_node.name or "", lang)
    test_content = _read_test_content(path)
    results = []
    for prod in prod_nodes:
        score = 0.0
        if path_convention_match(path, prod.path or "", lang):
            score += 0.30
        if _check_import(test_content, prod.path or ""):
            score += 0.30
        if name_match(stripped, prod.name or ""):
            score += 0.25
        if _has_direct_call_edge(test_node.id, prod.id, repo):
            score += 0.40
        if score >= MIN_CONFIDENCE:
            results.append((prod, score, "HIGH"))
        elif score >= MEDIUM_MIN_CONFIDENCE:
            results.append((prod, score, "MEDIUM"))
    return results


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class TestLinker:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def link_all(self, all_nodes: list[Node]) -> tuple[list, dict[str, list[str]]]:
        """Find TESTED_BY edges for all nodes.

        Returns:
            edges: list of TESTED_BY Edge objects (confidence >= MIN_CONFIDENCE)
            tags: dict of node_id -> ["tested"] for production nodes that have test coverage
        """
        from loom.graph.models.edge import ConfidenceTier, Edge, EdgeType

        # Separate test nodes from production nodes
        test_nodes: list[Node] = []
        prod_nodes: list[Node] = []

        for node in all_nodes:
            lang = node.language or ""
            if is_test_file(node.path or "", lang):
                test_nodes.append(node)
            else:
                prod_nodes.append(node)

        edges: list[Edge] = []
        tags: dict[str, list[str]] = {}

        for test_node in test_nodes:
            # Guard: skip test fixtures (conftest.py files, setUp methods)
            path = test_node.path or ""
            name = test_node.name or ""
            if "conftest" in path or name in (
                "setUp",
                "setUpClass",
                "tearDown",
                "tearDownClass",
            ):
                continue

            for prod, score, tier in match_test_to_production(test_node, prod_nodes, self.repo):
                if tier == "HIGH":
                    edges.append(
                        Edge(
                            from_id=test_node.id,
                            to_id=prod.id,
                            kind=EdgeType.TESTED_BY,
                            confidence=score,
                            confidence_tier=ConfidenceTier.INFERRED,
                        )
                    )
                    if prod.id not in tags:
                        tags[prod.id] = []
                    if "tested" not in tags[prod.id]:
                        tags[prod.id].append("tested")
                elif tier == "MEDIUM":
                    if prod.id not in tags:
                        tags[prod.id] = []
                    if "partially-tested" not in tags[prod.id]:
                        tags[prod.id].append("partially-tested")

        return edges, tags
