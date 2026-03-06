from __future__ import annotations

from pathlib import Path

from loom.ingest.code.languages.java import parse_java
from loom.ingest.code.languages.python import parse_python
from loom.ingest.code.languages.typescript import parse_typescript
from loom.ingest.code.languages.constants import META_REFLECTION_PATTERN


def test_python_parser_wires_dynamic_call_metadata(tmp_path: Path) -> None:
    p = tmp_path / "sample.py"
    p.write_text(
        """
def call_method(obj):
    return getattr(obj, \"run\")()
""".strip(),
        encoding="utf-8",
    )
    nodes = parse_python(str(p))
    func = next(n for n in nodes if n.name == "call_method")
    assert func.metadata.get(META_REFLECTION_PATTERN) == "getattr"


def test_java_parser_wires_reflection_metadata(tmp_path: Path) -> None:
    p = tmp_path / "Sample.java"
    p.write_text(
        """
class Sample {
    void load() throws Exception {
        Class.forName(\"com.example.Test\");
    }
}
""".strip(),
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    method = next(n for n in nodes if n.name == "load")
    assert method.metadata.get(META_REFLECTION_PATTERN) == "forName"


def test_typescript_parser_wires_dynamic_pattern_metadata(tmp_path: Path) -> None:
    p = tmp_path / "sample.ts"
    p.write_text(
        """
function loadModule() {
  return import(\"pkg\");
}
""".strip(),
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    func = next(n for n in nodes if n.name == "loadModule")
    assert func.metadata.get(META_REFLECTION_PATTERN) == "dynamic_import"
