"""Unit tests for the C++ structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.cpp import CppHandler

CPP_SRC = b"""
#include <string>

class Greeter {
public:
    Greeter(std::string n);
    std::string greet();
private:
    std::string name;
};

struct Point {
    int x;
    int y;
};

std::string Greeter::greet() {
    return "hi " + name;
}

int main() {
    return 0;
}
"""


def test_parse_cpp_basic():
    nodes = CppHandler().parse(CPP_SRC, "main.cpp")
    by_name_kind = [(n.name, n.kind) for n in nodes]
    assert any(name == "Greeter" and kind == NodeKind.CLASS for name, kind in by_name_kind)
    assert any(name == "Point" and kind == NodeKind.CLASS for name, kind in by_name_kind)
    assert any(name == "main" and kind == NodeKind.FUNCTION for name, kind in by_name_kind)
    assert any(kind == NodeKind.METHOD for _, kind in by_name_kind)


def test_parse_cpp_assigns_paths_and_language():
    nodes = CppHandler().parse(CPP_SRC, "main.cpp")
    assert all(n.path == "main.cpp" for n in nodes)
    assert all(n.language == "cpp" for n in nodes)


def test_parse_cpp_node_ids_have_correct_prefix():
    nodes = CppHandler().parse(CPP_SRC, "main.cpp")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_cpp_line_numbers_set():
    nodes = CppHandler().parse(CPP_SRC, "main.cpp")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
