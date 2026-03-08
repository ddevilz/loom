from __future__ import annotations

from pathlib import Path

from loom.core import EdgeType, NodeKind, NodeSource
from loom.ingest.docs.markdown import parse_markdown


def test_parse_markdown_creates_document_and_sections(tmp_path: Path) -> None:
    md = tmp_path / "spec.md"
    md.write_text(
        """
# Title

Intro text.

## Section A

Details.

### Sub A1

More.
""".strip(),
        encoding="utf-8",
    )

    nodes, edges = parse_markdown(str(md))

    assert nodes[0].kind == NodeKind.DOCUMENT
    assert nodes[0].source == NodeSource.DOC

    chapters = [n for n in nodes if n.kind == NodeKind.CHAPTER]
    sections = [n for n in nodes if n.kind == NodeKind.SECTION]
    subsections = [n for n in nodes if n.kind == NodeKind.SUBSECTION]
    paragraphs = [n for n in nodes if n.kind == NodeKind.PARAGRAPH]

    assert len(chapters) == 1
    assert len(sections) == 1
    assert len(subsections) == 1
    assert len(paragraphs) >= 3

    by_name = {n.name: n for n in [*chapters, *sections, *subsections]}
    assert by_name["Title"].depth == 1
    assert by_name["Section A"].depth == 2
    assert by_name["Sub A1"].depth == 3

    assert by_name["Title"].parent_id == nodes[0].id
    assert by_name["Section A"].parent_id == by_name["Title"].id
    assert by_name["Sub A1"].parent_id == by_name["Section A"].id

    assert by_name["Title"].summary is not None
    assert by_name["Section A"].summary is not None
    assert by_name["Sub A1"].summary is not None

    assert all(e.kind == EdgeType.CHILD_OF for e in edges)
    assert len(edges) >= 6

    # Ensure parent pointers exist
    assert all(s.parent_id is not None for s in [*chapters, *sections, *subsections, *paragraphs])


def test_parse_markdown_accepts_headings_with_up_to_three_leading_spaces(tmp_path: Path) -> None:
    md = tmp_path / "indented.md"
    md.write_text(
        """
   # Title

Body.

   ## Section A

Details.
""".strip(),
        encoding="utf-8",
    )

    nodes, _ = parse_markdown(str(md))

    assert any(node.kind == NodeKind.CHAPTER and node.name == "Title" for node in nodes)
    assert any(node.kind == NodeKind.SECTION and node.name == "Section A" for node in nodes)
