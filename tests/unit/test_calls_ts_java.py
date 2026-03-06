from __future__ import annotations

from pathlib import Path

from loom.analysis.code.calls_java import trace_calls_for_java_file
from loom.analysis.code.calls_ts import trace_calls_for_ts_file
from loom.analysis.code.parser import parse_code


def test_trace_calls_for_ts_file_extracts_calls(tmp_path: Path) -> None:
    p = tmp_path / "a.ts"
    p.write_text(
        """
function b() { return 1 }
function a() { b(); }
""".lstrip(),
        encoding="utf-8",
    )

    nodes = parse_code(str(p))
    edges = trace_calls_for_ts_file(str(p), nodes)

    assert any(e.kind.value == "calls" for e in edges)
    assert any("b" in e.to_id for e in edges)


def test_trace_calls_for_java_file_extracts_calls(tmp_path: Path) -> None:
    p = tmp_path / "A.java"
    p.write_text(
        """
class A {
  void b() {}
  void a() { b(); }
}
""".lstrip(),
        encoding="utf-8",
    )

    nodes = parse_code(str(p))
    edges = trace_calls_for_java_file(str(p), nodes)

    assert any(e.kind.value == "calls" for e in edges)
    assert any("b" in e.to_id for e in edges)
