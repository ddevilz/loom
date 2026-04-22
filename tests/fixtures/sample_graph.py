from __future__ import annotations

from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource


def build_sample_graph():
    # 15 function nodes in a single module
    functions = [
        "x",
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
        "h",
        "i",
        "j",
        "k",
        "validate_user",
        "parse_token",
        "hash_pw",
    ]

    func_nodes = [
        Node(
            id=f"function:src/sample.py:{name}",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name=name,
            path="src/sample.py",
            language="python",
            metadata={},
        )
        for name in functions
    ]

    # 2 doc sections
    doc_nodes = [
        Node(
            id="doc:spec.pdf:1.0",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="1.0",
            path="spec.pdf",
            metadata={},
        ),
        Node(
            id="doc:spec.pdf:2.0",
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name="2.0",
            path="spec.pdf",
            metadata={},
        ),
    ]

    nodes = func_nodes + doc_nodes

    fid = {n.name: n.id for n in func_nodes}

    edges: list[Edge] = []

    # CALLS edges
    calls = [
        ("x", "a"),
        ("x", "b"),
        ("x", "c"),
        ("a", "d"),
        ("a", "e"),
        ("b", "f"),
        ("b", "g"),
        ("c", "h"),
        ("h", "i"),
        ("i", "j"),
        ("validate_user", "parse_token"),
        ("validate_user", "hash_pw"),
        ("parse_token", "k"),
        ("hash_pw", "k"),
        ("d", "k"),
    ]

    for s, t in calls:
        edges.append(Edge(from_id=fid[s], to_id=fid[t], kind=EdgeType.CALLS))

    # Structural edge
    edges.append(
        Edge(from_id=fid["x"], to_id=fid["validate_user"], kind=EdgeType.IMPORTS)
    )

    assert len(func_nodes) == 15

    return {
        "nodes": nodes,
        "edges": edges,
        "function_ids": fid,
    }


def build_searchable_sample_graph():
    fixture = build_sample_graph()
    nodes: list[Node] = []
    for node in fixture["nodes"]:
        if node.id.endswith(":validate_user"):
            nodes.append(
                node.model_copy(
                    update={
                        "summary": "validate user authentication and enforce password policy",
                    }
                )
            )
        elif node.id == "doc:spec.pdf:1.0":
            nodes.append(
                node.model_copy(
                    update={
                        "summary": "authentication and password policy requirements",
                    }
                )
            )
        else:
            nodes.append(node.model_copy(update={"summary": node.name}))

    return {
        "nodes": nodes,
        "edges": fixture["edges"],
        "function_ids": fixture["function_ids"],
    }
