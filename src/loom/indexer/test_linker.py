"""TestLinker — post-parse pass that creates TESTED_BY edges.

This module is pure computation: it takes already-parsed nodes and returns
(edges, tags) without touching the database.  The pipeline is responsible for
persisting the result via repo.edges.upsert() and repo.tags.add_tags().
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    "python":     [("test_", "prefix"), ("_test", "suffix")],
    "typescript": [("test", "prefix_camel"), (".test", "file_suffix"), (".spec", "file_suffix")],
    "javascript": [("test", "prefix_camel"), (".test", "file_suffix"), (".spec", "file_suffix")],
    "java":       [("Test", "prefix_camel"), ("Test", "suffix"), ("Tests", "suffix"), ("IT", "suffix")],
}

MIN_CONFIDENCE = 0.55  # HIGH only — minimum 2 signals


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
            return name[len(pattern):]
        elif rule_type == "suffix" and name.endswith(pattern):
            return name[: -len(pattern)]
        elif rule_type == "prefix_camel":
            lower_name = name.lower()
            lower_pat = pattern.lower()
            if lower_name.startswith(lower_pat):
                stripped = name[len(pattern):]
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
                # The captured group(s) should appear in prod_path's basename
                base = m.group(1)
                if base in prod_path:
                    return True
        if p.dir_swap:
            test_dir, prod_dir = p.dir_swap
            if test_dir in test_path and prod_dir in prod_path:
                # Compare stems: TestFoo.java matches Foo.java
                return True
        if p.dir_re and p.mirror_src:
            if re.search(p.dir_re, test_path):
                # prod should be in mirror_src
                if p.mirror_src in prod_path:
                    return True
    return False


def imports_module(test_path: str, prod_path: str) -> bool:
    """Approximate import check — does prod_path's module name appear in test_path's stem?

    This is a heuristic: reads test file and checks if prod module name appears as an import.
    For performance, we check by reading the first 50 lines only.
    Falls back to False if file can't be read.
    """
    import os

    prod_module = os.path.splitext(os.path.basename(prod_path))[0]  # "auth" from "src/auth.py"
    try:
        with open(test_path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 50:
                    break
                if prod_module in line:
                    return True
    except OSError:
        return False
    return False


def name_match(stripped: str, prod_name: str) -> bool:
    """Return True if stripped test name matches production name (case-insensitive)."""
    return stripped.lower() == prod_name.lower()


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------


class TestLinker:
    def __init__(self, repo: "Repository") -> None:
        self.repo = repo

    def link_all(
        self, all_nodes: list["Node"]
    ) -> tuple[list, dict[str, list[str]]]:
        """Find TESTED_BY edges for all nodes.

        Returns:
            edges: list of TESTED_BY Edge objects (confidence >= MIN_CONFIDENCE)
            tags: dict of node_id -> ["tested"] for production nodes that have test coverage
        """
        from loom.graph.models.edge import Edge, EdgeType

        # Separate test nodes from production nodes
        test_nodes: list["Node"] = []
        prod_nodes: list["Node"] = []

        for node in all_nodes:
            lang = node.language or ""
            if is_test_file(node.path or "", lang):
                test_nodes.append(node)
            else:
                prod_nodes.append(node)

        edges: list[Edge] = []
        tags: dict[str, list[str]] = {}

        for test_node in test_nodes:
            lang = test_node.language or ""

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

            stripped = strip_test_name(name, lang)

            for prod in prod_nodes:
                score = 0.0

                if path_convention_match(path, prod.path or "", lang):
                    score += 0.3
                if imports_module(path, prod.path or ""):
                    score += 0.3
                if name_match(stripped, prod.name or ""):
                    score += 0.25

                if score >= MIN_CONFIDENCE:
                    edges.append(
                        Edge(
                            from_id=test_node.id,
                            to_id=prod.id,
                            kind=EdgeType.TESTED_BY,
                            confidence=score,
                        )
                    )
                    if prod.id not in tags:
                        tags[prod.id] = []
                    if "tested" not in tags[prod.id]:
                        tags[prod.id].append("tested")

        return edges, tags
