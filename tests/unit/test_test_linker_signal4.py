from unittest.mock import MagicMock

from loom.indexer.test_linker import MEDIUM_MIN_CONFIDENCE, MIN_CONFIDENCE


def test_thresholds():
    assert MIN_CONFIDENCE == 0.55
    assert MEDIUM_MIN_CONFIDENCE == 0.30


def test_signal4_alone_yields_medium():
    """CALLS edge alone (Signal 4 only, score=0.40) → MEDIUM tier."""
    from loom.graph.models import Node, NodeKind, NodeSource
    from loom.indexer.test_linker import match_test_to_production

    test_node = Node(
        id="function:r:tests/test_x.py:test_unrelated",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="test_unrelated",
        path="tests/test_x.py",
        language="python",
    )
    prod = Node(
        id="function:r:src/totally_different.py:something",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="something",
        path="src/totally_different.py",
        language="python",
    )
    repo = MagicMock()
    repo.edges.edge_exists.return_value = True

    matches = match_test_to_production(test_node, [prod], repo)
    assert any(tier == "MEDIUM" for _, _, tier in matches)


def test_signal4_plus_path_yields_high():
    """CALLS edge + path convention → score ≥ 0.55 → HIGH."""
    from loom.graph.models import Node, NodeKind, NodeSource
    from loom.indexer.test_linker import match_test_to_production

    test_node = Node(
        id="function:r:tests/test_foo.py:test_foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="test_foo",
        path="tests/test_foo.py",
        language="python",
    )
    prod = Node(
        id="function:r:src/foo.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="src/foo.py",
        language="python",
    )
    repo = MagicMock()
    repo.edges.edge_exists.return_value = True

    matches = match_test_to_production(test_node, [prod], repo)
    assert any(tier == "HIGH" for _, _, tier in matches)


def test_no_signals_yields_no_match():
    """No signals → not returned at all."""
    from loom.graph.models import Node, NodeKind, NodeSource
    from loom.indexer.test_linker import match_test_to_production

    test_node = Node(
        id="function:r:tests/test_a.py:test_something",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="test_something",
        path="tests/test_a.py",
        language="python",
    )
    prod = Node(
        id="function:r:src/b.py:completely_different",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="completely_different",
        path="src/b.py",
        language="python",
    )
    repo = MagicMock()
    repo.edges.edge_exists.return_value = False

    matches = match_test_to_production(test_node, [prod], repo)
    assert matches == []
