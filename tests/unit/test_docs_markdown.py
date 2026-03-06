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

    sec = [n for n in nodes if n.kind == NodeKind.SECTION]
    assert len(sec) == 3

    by_name = {n.name: n for n in sec}
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
    assert len(edges) == 3

    # Ensure parent pointers exist
    assert all(s.parent_id is not None for s in sec)
