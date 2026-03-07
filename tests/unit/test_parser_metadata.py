from __future__ import annotations

from pathlib import Path

from loom.ingest.code.languages.java import parse_java
from loom.ingest.code.languages.python import parse_python
from loom.ingest.code.languages.typescript import parse_typescript


def test_python_parser_emits_signature_metadata(tmp_path: Path) -> None:
    p = tmp_path / "sample.py"
    p.write_text(
        """
def add(x: int, y: int) -> int:
    return x + y
""".strip(),
        encoding="utf-8",
    )
    node = next(n for n in parse_python(str(p)) if n.name == "add")
    assert node.metadata["params"]
    assert node.metadata["return_type"] == "int"
    assert "add(" in node.metadata["signature"]
    assert "return x + y" in node.metadata["source_text"]


def test_java_parser_emits_signature_metadata(tmp_path: Path) -> None:
    p = tmp_path / "Sample.java"
    p.write_text(
        """
class Sample {
    int add(int x, int y) {
        return x + y;
    }
}
""".strip(),
        encoding="utf-8",
    )
    node = next(n for n in parse_java(str(p)) if n.name == "add")
    assert node.metadata["params"]
    assert node.metadata["return_type"] == "int"
    assert "add(" in node.metadata["signature"]
    assert "return x + y;" in node.metadata["source_text"]


def test_typescript_parser_emits_signature_metadata(tmp_path: Path) -> None:
    p = tmp_path / "sample.ts"
    p.write_text(
        """
function add(x: number, y: number): number {
  return x + y;
}
""".strip(),
        encoding="utf-8",
    )
    node = next(n for n in parse_typescript(str(p)) if n.name == "add")
    assert node.metadata["params"]
    assert node.metadata["return_type"] == "number"
    assert "add(" in node.metadata["signature"]
    assert "return x + y;" in node.metadata["source_text"]
