"""Unit tests for the Rust structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.rust import RustHandler

RUST_SRC = b"""
struct Greeter {
    name: String,
}

enum Color {
    Red,
    Blue,
}

trait Sayer {
    fn say(&self) -> String;
}

impl Sayer for Greeter {
    fn say(&self) -> String {
        format!("hi {}", self.name)
    }
}

fn main() {
    let g = Greeter { name: "world".into() };
    println!("{}", g.say());
}
"""


def test_parse_rust_extracts_all_kinds():
    nodes = RustHandler().parse(RUST_SRC, "main.rs")
    by_name = {n.name: n.kind for n in nodes}
    assert by_name["Greeter"] == NodeKind.CLASS
    assert by_name["Color"] == NodeKind.CLASS
    assert by_name["Sayer"] == NodeKind.INTERFACE
    assert by_name["main"] == NodeKind.FUNCTION
    assert any(n.kind == NodeKind.METHOD and n.name == "say" for n in nodes)


def test_parse_rust_assigns_paths_and_language():
    nodes = RustHandler().parse(RUST_SRC, "main.rs")
    assert all(n.path == "main.rs" for n in nodes)
    assert all(n.language == "rust" for n in nodes)


def test_parse_rust_node_ids_have_correct_prefix():
    nodes = RustHandler().parse(RUST_SRC, "main.rs")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_rust_line_numbers_set():
    nodes = RustHandler().parse(RUST_SRC, "main.rs")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
