from loom.indexer.graph_tagger import _compute_bridge_scores


def test_brandes_path_graph_center_highest():
    """In path graph A-B-C-D-E, the middle node should have highest betweenness."""
    nodes = ["A", "B", "C", "D", "E"]
    edges = [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]
    scores = _compute_bridge_scores(nodes, edges)
    assert scores["C"] > scores["B"]
    assert scores["C"] > scores["A"]


def test_brandes_star_graph_normalization():
    """Star graph: center has betweenness ~1.0 (after normalization), leaves 0.0."""
    nodes = ["C", "A", "B", "D", "E"]
    edges = [("C", "A"), ("C", "B"), ("C", "D"), ("C", "E")]
    scores = _compute_bridge_scores(nodes, edges)
    assert scores["C"] > 0.99
    assert scores["A"] < 0.01


def test_brandes_returns_empty_above_limit():
    nodes = [f"n{i}" for i in range(3000)]
    edges = []
    scores = _compute_bridge_scores(nodes, edges)
    assert scores == {}


def test_brandes_returns_empty_too_small():
    assert _compute_bridge_scores(["A", "B"], [("A", "B")]) == {}


def test_brandes_disconnected_graph():
    """Disconnected graph: isolated nodes have 0 betweenness."""
    nodes = ["A", "B", "C", "D", "E"]
    edges = [("A", "B"), ("D", "E")]
    scores = _compute_bridge_scores(nodes, edges)
    # C is fully isolated
    assert scores["C"] == 0.0
    # All scores in [0, 1]
    assert all(0.0 <= v <= 1.0 for v in scores.values())
