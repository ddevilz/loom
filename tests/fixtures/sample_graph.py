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

    # CALLS edges (exactly 20 total edges overall will be enforced below)
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
    ]

    for s, t in calls:
        edges.append(Edge(from_id=fid[s], to_id=fid[t], kind=EdgeType.CALLS))

    # A few non-calls structural edges
    edges.extend(
        [
            Edge(from_id=fid["x"], to_id=fid["validate_user"], kind=EdgeType.IMPORTS),
            Edge(from_id=fid["validate_user"], to_id=fid["hash_pw"], kind=EdgeType.USES_TYPE),
        ]
    )

    # Cross-domain links (use LOOM_* edges)
    edges.extend(
        [
            Edge(
                from_id=fid["validate_user"],
                to_id="doc:spec.pdf:1.0",
                kind=EdgeType.LOOM_IMPLEMENTS,
                confidence=0.8,
                link_method="name_match",
                link_reason="validate_user mentioned in spec section 1.0",
                metadata={"score": 0.8},
            ),
            Edge(
                from_id=fid["parse_token"],
                to_id="doc:spec.pdf:2.0",
                kind=EdgeType.LOOM_SPECIFIES,
                confidence=0.6,
                link_method="embed_match",
                link_reason="embedding similarity",
                metadata={"score": 0.6},
            ),
        ]
    )

    # Structural cross-domain IMPLEMENTS edge (Function -> Section) to satisfy the acceptance Cypher query.
    edges.append(
        Edge(
            from_id=fid["validate_user"],
            to_id="doc:spec.pdf:1.0",
            kind=EdgeType.IMPLEMENTS,
        )
    )

    # Ensure we have exactly 20 edges by adding a few extra CALLS
    extras = [
        ("d", "k"),
    ]
    for s, t in extras:
        edges.append(Edge(from_id=fid[s], to_id=fid[t], kind=EdgeType.CALLS))

    assert len(func_nodes) == 15
    assert len(edges) == 20

    return {
        "nodes": nodes,
        "edges": edges,
        "function_ids": fid,
    }
