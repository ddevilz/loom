from __future__ import annotations

from pathlib import Path

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes


def _slug(s: str) -> str:
    out = []
    prev_dash = False
    for ch in s.strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    slug = "".join(out).strip("-")
    return slug or "section"


def make_document_node(path: str) -> Node:
    p = Path(path)
    ch = content_hash_bytes(p.read_bytes())
    return Node(
        id=f"doc:{path}:root",
        kind=NodeKind.DOCUMENT,
        source=NodeSource.DOC,
        name=p.name,
        path=path,
        content_hash=ch,
        summary=None,
        metadata={},
    )


def make_section_node(*, doc_path: str, heading: str, depth: int, index: int, summary: str | None) -> Node:
    ref = f"{depth}_{index}_{_slug(heading)}"
    return Node(
        id=f"doc:{doc_path}:{ref}",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=heading,
        path=doc_path,
        depth=depth,
        parent_id=None,
        summary=summary,
        metadata={},
    )


def make_child_of(child_id: str, parent_id: str) -> Edge:
    return Edge(
        from_id=child_id,
        to_id=parent_id,
        kind=EdgeType.CHILD_OF,
        origin=EdgeOrigin.COMPUTED,
        confidence=1.0,
        metadata={},
    )


def walk_docs(docs_path: str) -> tuple[list[Node], list[Edge]]:
    root = Path(docs_path)
    nodes: list[Node] = []
    edges: list[Edge] = []

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in {".md", ".markdown"}:
            from .markdown import parse_markdown

            n, e = parse_markdown(str(p))
            nodes.extend(n)
            edges.extend(e)
        elif ext == ".pdf":
            from .pdf import parse_pdf

            n, e = parse_pdf(str(p))
            nodes.extend(n)
            edges.extend(e)

    return nodes, edges
