"""Unit tests for AutoTagger — decorator, import, and directory tag pass."""

from __future__ import annotations

import pytest

from loom.graph.models.node import Node, NodeKind, NodeSource
from loom.indexer.tagger import AutoTagger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_node(
    name: str = "func",
    kind: NodeKind = NodeKind.FUNCTION,
    path: str = "src/foo.py",
    decorators: list[str] | None = None,
) -> Node:
    metadata: dict = {}
    if decorators is not None:
        metadata["decorators"] = decorators
    return Node(
        id=f"{kind.value}:{path}:{name}",
        kind=kind,
        source=NodeSource.CODE,
        name=name,
        path=path,
        metadata=metadata,
    )


@pytest.fixture
def tagger() -> AutoTagger:
    return AutoTagger()


# ---------------------------------------------------------------------------
# Test 1: Decorator tag applied to correct node only
# ---------------------------------------------------------------------------


def test_decorator_tag_correct_node(tagger: AutoTagger) -> None:
    """Node with @pytest.fixture gets 'test-fixture'; other nodes don't."""
    fixture_node = make_node("setup", decorators=["@pytest.fixture"])
    plain_node = make_node("helper", decorators=[])

    result = tagger.tag_file([fixture_node, plain_node], imports=[], path="tests/test_foo.py")

    assert "test-fixture" in result[fixture_node.id]
    assert "test-fixture" not in result[plain_node.id]


# ---------------------------------------------------------------------------
# Test 2: Router prefix matching (@router. prefix)
# ---------------------------------------------------------------------------


def test_router_prefix_match(tagger: AutoTagger) -> None:
    """@router.get('/users') should match the '@router.' prefix key -> 'api-endpoint'."""
    node = make_node("get_users", decorators=["@router.get('/users')"])

    result = tagger.tag_file([node], imports=[], path="src/routes.py")

    assert "api-endpoint" in result[node.id]


# ---------------------------------------------------------------------------
# Test 3: Import tags applied to ALL nodes in the file
# ---------------------------------------------------------------------------


def test_import_tags_applied_to_all_nodes(tagger: AutoTagger) -> None:
    """File importing sqlalchemy -> all nodes get ['database', 'orm']."""
    node_a = make_node("Model")
    node_b = make_node("session_factory")

    result = tagger.tag_file(
        [node_a, node_b],
        imports=["from sqlalchemy import Column", "import sqlalchemy.orm"],
        path="src/db.py",
    )

    for node in (node_a, node_b):
        assert "database" in result[node.id], f"Expected 'database' for {node.id}"
        assert "orm" in result[node.id], f"Expected 'orm' for {node.id}"


# ---------------------------------------------------------------------------
# Test 4: Dir tag — middleware path
# ---------------------------------------------------------------------------


def test_dir_tag_middleware(tagger: AutoTagger) -> None:
    """Path segment 'middleware' -> all nodes get 'middleware' tag."""
    node = make_node("auth_middleware")

    result = tagger.tag_file([node], imports=[], path="src/middleware/auth.py")

    assert "middleware" in result[node.id]


# ---------------------------------------------------------------------------
# Test 5: Dir tag — helpers path -> utility
# ---------------------------------------------------------------------------


def test_dir_tag_helpers(tagger: AutoTagger) -> None:
    """Path segment 'helpers' -> all nodes get 'utility' tag."""
    node = make_node("format_date")

    result = tagger.tag_file([node], imports=[], path="app/helpers/format.py")

    assert "utility" in result[node.id]


# ---------------------------------------------------------------------------
# Test 6: No tags when nothing matches
# ---------------------------------------------------------------------------


def test_no_tags_when_no_match(tagger: AutoTagger) -> None:
    """No matching decorators, imports, or directory segments -> empty tag lists."""
    node = make_node("process_data", decorators=["@my_custom_decorator"])

    result = tagger.tag_file(
        [node],
        imports=["import os", "import sys"],
        path="src/core/processor.py",
    )

    assert result[node.id] == []


# ---------------------------------------------------------------------------
# Test 7: Multiple sources combine on the same node
# ---------------------------------------------------------------------------


def test_multiple_sources_combine(tagger: AutoTagger) -> None:
    """Node with a decorator + matching import + matching dir path gets all tags."""
    node = make_node(
        "create_user",
        decorators=["@app.route('/users', methods=['POST'])"],
        path="src/middleware/users.py",
    )

    result = tagger.tag_file(
        [node],
        imports=["import jwt"],
        path="src/middleware/users.py",
    )

    tags = result[node.id]
    assert "api-endpoint" in tags, "expected decorator tag api-endpoint"
    assert "auth" in tags, "expected import tag auth (from jwt)"
    assert "jwt" in tags, "expected import tag jwt"
    assert "middleware" in tags, "expected dir tag middleware"


# ---------------------------------------------------------------------------
# Test 8: metadata=None (or empty dict) handled gracefully
# ---------------------------------------------------------------------------


def test_node_with_no_metadata_handled_gracefully(tagger: AutoTagger) -> None:
    """Node with empty metadata dict (no 'decorators' key) should not raise."""
    node = make_node("bare_func")
    # metadata is {} (no 'decorators' key) — created by make_node with decorators=None

    result = tagger.tag_file([node], imports=[], path="src/foo.py")

    # Should just be an empty list (no error raised)
    assert isinstance(result[node.id], list)


# ---------------------------------------------------------------------------
# Test 9: Windows-style path separators
# ---------------------------------------------------------------------------


def test_windows_path_separator(tagger: AutoTagger) -> None:
    """Backslash-separated paths should still match dir tags."""
    node = make_node("do_work")

    result = tagger.tag_file([node], imports=[], path=r"app\workers\email.py")

    assert "async-worker" in result[node.id]


# ---------------------------------------------------------------------------
# Test 10: Exact decorator match doesn't bleed into similar names
# ---------------------------------------------------------------------------


def test_staticmethod_exact_match(tagger: AutoTagger) -> None:
    """@staticmethod key should match exactly and return 'static' tag."""
    node = make_node("my_func", decorators=["@staticmethod"])

    result = tagger.tag_file([node], imports=[], path="src/utils.py")

    assert "static" in result[node.id]


# ---------------------------------------------------------------------------
# Test 11: Empty nodes list
# ---------------------------------------------------------------------------


def test_empty_nodes_list(tagger: AutoTagger) -> None:
    """Empty nodes list should return empty dict."""
    result = tagger.tag_file([], [], "src/utils/foo.py")

    assert result == {}
