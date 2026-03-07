from __future__ import annotations

from pathlib import Path
from typing import Callable

from loom.core import Edge, EdgeOrigin, EdgeType, Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes


DocParser = Callable[[str], tuple[list[Node], list[Edge]]]
_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})


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


def make_section_node(
    *,
    doc_path: str,
    heading: str,
    depth: int,
    index: int,
    summary: str | None,
    kind: NodeKind = NodeKind.SECTION,
) -> Node:
    ref = f"{depth}_{index}_{_slug(heading)}"
    return Node(
        id=f"doc:{doc_path}:{ref}",
        kind=kind,
        source=NodeSource.DOC,
        name=heading,
        path=doc_path,
        depth=depth,
        parent_id=None,
        summary=summary,
        metadata={},
    )


def make_paragraph_node(*, doc_path: str, parent_ref: str, index: int, text: str) -> Node:
    return Node(
        id=f"doc:{doc_path}:{parent_ref}:p{index}",
        kind=NodeKind.PARAGRAPH,
        source=NodeSource.DOC,
        name=f"paragraph_{index}",
        path=doc_path,
        summary=text,
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


def _get_doc_parser(path: Path) -> DocParser | None:
    ext = path.suffix.lower()
    if ext in _MARKDOWN_EXTENSIONS:
        from .markdown import parse_markdown

        return parse_markdown
    if ext == ".pdf":
        from .pdf import parse_pdf

        return parse_pdf
    return None


def walk_docs(docs_path: str) -> tuple[list[Node], list[Edge]]:
    root = Path(docs_path)
    nodes: list[Node] = []
    edges: list[Edge] = []

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        parser = _get_doc_parser(p)
        if parser is None:
            continue
        n, e = parser(str(p))
        nodes.extend(n)
        edges.extend(e)

    return nodes, edges
