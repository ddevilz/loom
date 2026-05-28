def test_import_from_graph():
    from loom.graph import Edge, Node

    assert Node is not None
    assert Edge is not None


def test_import_from_graph_models():
    from loom.graph.models import Node, SummarySource

    assert Node is not None
    assert SummarySource is not None
