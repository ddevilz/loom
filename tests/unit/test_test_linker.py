"""Unit tests for TestLinker — TESTED_BY edge creation pass."""

from __future__ import annotations

from unittest.mock import patch

from loom.graph.models.node import Node, NodeKind, NodeSource
from loom.indexer.test_linker import (
    TestLinker,
    is_test_file,
    name_match,
    path_convention_match,
    strip_test_name,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_node(
    name: str,
    path: str,
    language: str = "python",
    kind: NodeKind = NodeKind.FUNCTION,
) -> Node:
    return Node(
        id=f"{kind.value}:{path}:{name}",
        kind=kind,
        source=NodeSource.CODE,
        name=name,
        path=path,
        language=language,
    )


# ---------------------------------------------------------------------------
# Test 1: is_test_file — Python
# ---------------------------------------------------------------------------


def test_is_test_file_python_true() -> None:
    """tests/test_auth.py is a test file for Python."""
    assert is_test_file("tests/test_auth.py", "python") is True


def test_is_test_file_python_false() -> None:
    """src/auth.py is NOT a test file for Python."""
    assert is_test_file("src/auth.py", "python") is False


# ---------------------------------------------------------------------------
# Test 2: is_test_file — TypeScript
# ---------------------------------------------------------------------------


def test_is_test_file_typescript_true() -> None:
    """auth.test.ts is a test file for TypeScript."""
    assert is_test_file("auth.test.ts", "typescript") is True


def test_is_test_file_typescript_false() -> None:
    """auth.ts is NOT a test file for TypeScript."""
    assert is_test_file("auth.ts", "typescript") is False


# ---------------------------------------------------------------------------
# Test 3: strip_test_name — Python prefix
# ---------------------------------------------------------------------------


def test_strip_test_name_python_prefix() -> None:
    """test_validate_token -> validate_token (strip test_ prefix)."""
    assert strip_test_name("test_validate_token", "python") == "validate_token"


# ---------------------------------------------------------------------------
# Test 4: strip_test_name — Python suffix
# ---------------------------------------------------------------------------


def test_strip_test_name_python_suffix() -> None:
    """validate_token_test -> validate_token (strip _test suffix)."""
    assert strip_test_name("validate_token_test", "python") == "validate_token"


# ---------------------------------------------------------------------------
# Test 5: strip_test_name — Java camel
# ---------------------------------------------------------------------------


def test_strip_test_name_java_camel() -> None:
    """TestFoo -> Foo (strip Test prefix, capitalize next char)."""
    assert strip_test_name("TestFoo", "java") == "Foo"


# ---------------------------------------------------------------------------
# Test 6: path_convention_match — Python
# ---------------------------------------------------------------------------


def test_path_convention_match_python() -> None:
    """tests/test_auth.py matches src/auth.py via Python conventions."""
    assert path_convention_match("tests/test_auth.py", "src/auth.py", "python") is True


def test_path_convention_match_python_no_match() -> None:
    """A test file in tests/ does NOT match a prod file not in src/ with a different name."""
    assert path_convention_match("tests/test_auth.py", "app/users.py", "python") is False


# ---------------------------------------------------------------------------
# Test 7: name_match — case-insensitive
# ---------------------------------------------------------------------------


def test_name_match_case_insensitive() -> None:
    """validateToken vs ValidateToken -> True (case-insensitive)."""
    assert name_match("validateToken", "ValidateToken") is True


def test_name_match_different_names() -> None:
    """validateToken vs createUser -> False."""
    assert name_match("validateToken", "createUser") is False


# ---------------------------------------------------------------------------
# Test 8: link_all integration — path convention + name match = 0.55
# ---------------------------------------------------------------------------


def test_link_all_integration_path_and_name_match() -> None:
    """One test node + one prod node linked by convention + name match.

    Path convention gives 0.3, name match gives 0.25 = 0.55 total.
    Exactly one TESTED_BY edge with confidence 0.55 should be returned,
    and prod.id should appear in the tags dict.
    """
    test_node = make_node(
        name="test_validate_token",
        path="tests/test_auth.py",
        language="python",
    )
    prod_node = make_node(
        name="validate_token",
        path="src/auth.py",
        language="python",
    )

    # TestLinker.link_all does not write to DB — pass None as repo
    linker = TestLinker(repo=None)  # type: ignore[arg-type]
    with patch("loom.indexer.test_linker._read_test_content", return_value=""):
        edges, tags = linker.link_all([test_node, prod_node])

    assert len(edges) == 1, f"Expected 1 edge, got {len(edges)}"
    edge = edges[0]

    assert edge.from_id == test_node.id
    assert edge.to_id == prod_node.id
    assert edge.kind.value == "TESTED_BY"
    assert abs(edge.confidence - 0.55) < 1e-9, f"Expected 0.55, got {edge.confidence}"

    assert prod_node.id in tags
    assert "tested" in tags[prod_node.id]


# ---------------------------------------------------------------------------
# Test 9: link_all — conftest.py files are skipped
# ---------------------------------------------------------------------------


def test_link_all_skips_conftest() -> None:
    """Nodes in conftest.py should not generate edges."""
    conftest_node = make_node(
        name="fixture_db",
        path="tests/conftest.py",
        language="python",
    )
    prod_node = make_node(
        name="fixture_db",
        path="src/db.py",
        language="python",
    )

    linker = TestLinker(repo=None)  # type: ignore[arg-type]
    with patch("loom.indexer.test_linker._read_test_content", return_value=""):
        edges, tags = linker.link_all([conftest_node, prod_node])

    assert edges == []
    assert tags == {}


# ---------------------------------------------------------------------------
# Test 10: link_all — setUp / tearDown lifecycle methods skipped
# ---------------------------------------------------------------------------


def test_link_all_skips_setup_teardown() -> None:
    """setUp and tearDown test lifecycle methods should not generate edges."""
    setup_node = make_node(
        name="setUp",
        path="tests/test_auth.py",
        language="python",
    )
    prod_node = make_node(
        name="setUp",
        path="src/auth.py",
        language="python",
    )

    linker = TestLinker(repo=None)  # type: ignore[arg-type]
    with patch("loom.indexer.test_linker._read_test_content", return_value=""):
        edges, tags = linker.link_all([setup_node, prod_node])

    assert edges == []
    assert tags == {}


# ---------------------------------------------------------------------------
# Test 11: link_all — below threshold, no edge emitted
# ---------------------------------------------------------------------------


def test_link_all_below_threshold_no_edge() -> None:
    """Only name match (0.25) < MIN_CONFIDENCE (0.55) — no edge emitted.

    Use a prod path not under src/ so the dir_re mirror rule doesn't fire.
    """
    test_node = make_node(
        name="test_bar",
        path="tests/test_bar.py",
        language="python",
    )
    prod_node = make_node(
        name="baz",
        path="app/baz.py",
        language="python",
    )

    linker = TestLinker(repo=None)  # type: ignore[arg-type]
    with patch("loom.indexer.test_linker._read_test_content", return_value=""):
        edges, tags = linker.link_all([test_node, prod_node])

    assert edges == []
    assert tags == {}


# ---------------------------------------------------------------------------
# Test 12: TypeScript spec file recognised as test
# ---------------------------------------------------------------------------


def test_is_test_file_spec_ts() -> None:
    """auth.spec.ts is also a test file for TypeScript."""
    assert is_test_file("src/auth.spec.ts", "typescript") is True


# ---------------------------------------------------------------------------
# Test 13: Java test class via dir_swap convention
# ---------------------------------------------------------------------------


def test_path_convention_match_java_dir_swap() -> None:
    """src/test/java/Foo matches src/main/java/Foo via dir_swap."""
    assert (
        path_convention_match(
            "src/test/java/FooTest.java",
            "src/main/java/Foo.java",
            "java",
        )
        is True
    )


# ---------------------------------------------------------------------------
# Test 14: strip_test_name — no rule matches returns original
# ---------------------------------------------------------------------------


def test_strip_test_name_no_match_returns_original() -> None:
    """A name without a test prefix/suffix is returned unchanged."""
    assert strip_test_name("validate_token", "python") == "validate_token"
