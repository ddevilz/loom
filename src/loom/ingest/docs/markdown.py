from __future__ import annotations

from pathlib import Path

from loom.core import Edge, Node, NodeKind

from .base import make_child_of, make_document_node, make_paragraph_node, make_section_node


def _kind_for_depth(depth: int) -> NodeKind:
    if depth <= 1:
        return NodeKind.CHAPTER
    if depth == 2:
        return NodeKind.SECTION
    return NodeKind.SUBSECTION


def _paragraphs(body: str | None) -> list[str]:
    if not body:
        return []
    return [part.strip() for part in body.split("\n\n") if part.strip()]


def parse_markdown(path: str) -> tuple[list[Node], list[Edge]]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")

    doc = make_document_node(str(p))
    nodes: list[Node] = [doc]
    edges: list[Edge] = []

    headings: list[tuple[int, str, int]] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            continue
        hashes = len(line) - len(line.lstrip("#"))
        title = line[hashes:].strip()
        if not title:
            continue
        headings.append((hashes, title, i))

    stack: list[tuple[int, str]] = [(0, doc.id)]
    for idx, (depth, title, start_line) in enumerate(headings, start=1):
        # capture body until next heading
        end_line = headings[idx][2] if idx < len(headings) else len(lines)
        body = "\n".join(lines[start_line + 1 : end_line]).strip() or None

        n = make_section_node(
            doc_path=str(p),
            heading=title,
            depth=depth,
            index=idx,
            summary=body,
            kind=_kind_for_depth(depth),
        )
        nodes.append(n)

        while stack and stack[-1][0] >= depth:
            stack.pop()
        parent_id = stack[-1][1] if stack else doc.id

        n = n.model_copy(update={"parent_id": parent_id})
        nodes[-1] = n
        edges.append(make_child_of(n.id, parent_id))
        stack.append((depth, n.id))

        for paragraph_index, paragraph_text in enumerate(_paragraphs(body), start=1):
            paragraph = make_paragraph_node(
                doc_path=str(p),
                parent_ref=n.id.rsplit(":", 1)[-1],
                index=paragraph_index,
                text=paragraph_text,
            ).model_copy(update={"parent_id": n.id})
            nodes.append(paragraph)
            edges.append(make_child_of(paragraph.id, n.id))

    return nodes, edges
