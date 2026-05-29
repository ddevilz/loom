"""Unit tests for the C# structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.csharp import CSharpHandler

CS_SRC = b"""
namespace App {
    public interface IGreeter { string Say(); }

    public class Greeter : IGreeter {
        private string _name;

        public Greeter(string name) { _name = name; }

        public string Say() => "hi " + _name;
    }

    public struct Point { public int X; public int Y; }

    public record Box(int W, int H);
}
"""


def test_parse_csharp_basic():
    nodes = CSharpHandler().parse(CS_SRC, "App.cs")
    # Use set of (name, kind) tuples to handle name collisions (e.g. class Greeter + constructor Greeter)
    name_kinds = {(n.name, n.kind) for n in nodes}
    assert ("IGreeter", NodeKind.INTERFACE) in name_kinds
    assert ("Greeter", NodeKind.CLASS) in name_kinds
    assert ("Point", NodeKind.CLASS) in name_kinds
    assert ("Box", NodeKind.CLASS) in name_kinds
    assert any(n.kind == NodeKind.METHOD and n.name == "Say" for n in nodes)
    assert any(n.kind == NodeKind.FUNCTION and n.name == "Greeter" for n in nodes)


def test_parse_csharp_assigns_paths_and_language():
    nodes = CSharpHandler().parse(CS_SRC, "App.cs")
    assert all(n.path == "App.cs" for n in nodes)
    assert all(n.language == "csharp" for n in nodes)


def test_parse_csharp_node_ids_have_correct_prefix():
    nodes = CSharpHandler().parse(CS_SRC, "App.cs")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_csharp_line_numbers_set():
    nodes = CSharpHandler().parse(CS_SRC, "App.cs")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
