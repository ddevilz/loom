"""Unit tests for the Go structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.go import GoHandler


def parse_go(src: bytes, path: str) -> list:
    """Helper: parse Go source bytes directly."""
    return GoHandler().parse(src, path)

GO_SRC = b"""package main

import "fmt"

type Greeter struct {
\tName string
}

type Sayer interface {
\tSay() string
}

func (g *Greeter) Greet() string {
\treturn "hi " + g.Name
}

func main() {
\tg := &Greeter{Name: "world"}
\tfmt.Println(g.Greet())
}
"""


def test_parse_go_extracts_function_and_method_and_class():
    nodes = GoHandler().parse(GO_SRC, "main.go")
    kinds = {(n.kind, n.name) for n in nodes}
    assert (NodeKind.CLASS, "Greeter") in kinds
    assert (NodeKind.INTERFACE, "Sayer") in kinds
    assert (NodeKind.METHOD, "Greet") in kinds
    assert (NodeKind.FUNCTION, "main") in kinds


def test_parse_go_assigns_paths_and_language():
    nodes = GoHandler().parse(GO_SRC, "main.go")
    assert all(n.path == "main.go" for n in nodes)
    assert all(n.language == "go" for n in nodes)


def test_parse_go_node_ids_have_correct_prefix():
    nodes = GoHandler().parse(GO_SRC, "main.go")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_go_line_numbers_set():
    nodes = GoHandler().parse(GO_SRC, "main.go")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line


def test_parse_go_no_method_id_collision():
    """Two methods with same name on different types should have different IDs."""
    src = b"""package main
type Foo struct{}
type Bar struct{}
func (f Foo) String() string { return "foo" }
func (b Bar) String() string { return "bar" }
"""
    nodes = parse_go(src, "types.go")
    methods = [n for n in nodes if n.name == "String"]
    assert len(methods) == 2
    assert methods[0].id != methods[1].id
