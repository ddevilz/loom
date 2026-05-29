"""complexity.py — function complexity classification from tree-sitter AST metrics.

Calibrated against Loom codebase (415 functions): p50=13 lines, p90=58 lines.
Thresholds target top ~10% as COMPLEX.
"""

from __future__ import annotations

from tree_sitter import Node as TSNode

from loom.graph.models.enums import Complexity

# Threshold constants — tune these without touching logic
COMPLEX_BRANCHES = 8
COMPLEX_NESTING = 4
COMPLEX_LINES = 60
SIMPLE_BRANCHES = 3
SIMPLE_NESTING = 2
SIMPLE_LINES = 25

# OR for COMPLEX (any one signal sufficient), AND for SIMPLE (all three must be low)
BRIDGE_MIN_INDEGREE = 3  # used by GraphTagger
BRIDGE_MIN_OUTDEGREE = 3

BRANCH_NODES: dict[str, set[str]] = {
    "python": {
        "if_statement",
        "for_statement",
        "while_statement",
        "try_statement",
        "except_clause",
        "match_statement",
        "case_clause",
        "conditional_expression",
        "boolean_operator",
    },
    "typescript": {
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "switch_statement",
        "case",
        "try_statement",
        "catch_clause",
        "ternary_expression",
    },
    "javascript": {
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "switch_statement",
        "case",
        "try_statement",
        "catch_clause",
        "ternary_expression",
    },
    "java": {
        "if_statement",
        "for_statement",
        "while_statement",
        "enhanced_for_statement",
        "switch_expression",
        "case",
        "try_statement",
        "catch_clause",
        "ternary_expression",
    },
}


def count_branch_nodes(ts_node: TSNode, language: str) -> int:
    """Count branch/decision points in a tree-sitter AST node."""
    from loom.indexer.languages._ts_utils import walk_all  # local import avoids circular dep

    branch_types = BRANCH_NODES.get(language, set())
    return sum(1 for n in walk_all(ts_node) if n.type in branch_types)


def compute_max_nesting(ts_node: TSNode, language: str) -> int:
    """Walk tree-sitter AST, track max nesting depth of control flow."""
    branch_types = BRANCH_NODES.get(language, set())

    def _walk_depth(n: TSNode, depth: int) -> int:
        current = depth + 1 if n.type in branch_types else depth
        max_depth = current
        for child in n.children:
            child_depth = _walk_depth(child, current)
            if child_depth > max_depth:
                max_depth = child_depth
        return max_depth

    return _walk_depth(ts_node, 0)


def classify_complexity(ts_node: TSNode, language: str) -> Complexity:
    """Classify function complexity from tree-sitter metrics.

    Uses OR for COMPLEX (any signal sufficient) and AND for SIMPLE (all must be low).
    """
    branches = count_branch_nodes(ts_node, language)
    nesting = compute_max_nesting(ts_node, language)
    lines = ts_node.end_point[0] - ts_node.start_point[0]

    if branches >= COMPLEX_BRANCHES or nesting >= COMPLEX_NESTING or lines >= COMPLEX_LINES:
        return Complexity.COMPLEX
    if branches <= SIMPLE_BRANCHES and nesting <= SIMPLE_NESTING and lines <= SIMPLE_LINES:
        return Complexity.SIMPLE
    return Complexity.MODERATE
