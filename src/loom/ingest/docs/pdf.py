from __future__ import annotations

from pathlib import Path

from loom.core import Edge, Node, NodeKind, NodeSource

from .base import make_child_of, make_document_node


def parse_pdf(path: str) -> tuple[list[Node], list[Edge]]:
    # Minimal implementation: requires pypdf at runtime.
    from pypdf import PdfReader  # type: ignore

    p = Path(path)
    reader = PdfReader(str(p))

    doc = make_document_node(str(p))
    nodes: list[Node] = [doc]
    edges: list[Edge] = []

    for i, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        summary = txt.strip() or None
        page_id = f"doc:{str(p)}:page_{i}"
        n = Node(
            id=page_id,
            kind=NodeKind.SECTION,
            source=NodeSource.DOC,
            name=f"page_{i}",
            path=str(p),
            depth=1,
            parent_id=doc.id,
            page_start=i,
            page_end=i,
            summary=summary,
            metadata={},
        )
        nodes.append(n)
        edges.append(make_child_of(n.id, doc.id))

    return nodes, edges
