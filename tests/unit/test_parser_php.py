"""Unit tests for the PHP structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.php import PhpHandler

PHP_SRC = b"""<?php
interface Sayer {
    public function say(): string;
}

class Greeter implements Sayer {
    private $name;

    public function __construct($name) {
        $this->name = $name;
    }

    public function say(): string {
        return "hi " . $this->name;
    }
}

function shout($msg) {
    return strtoupper($msg);
}
"""


def test_parse_php_basic():
    nodes = PhpHandler().parse(PHP_SRC, "greet.php")
    by_name = {n.name: n.kind for n in nodes}
    assert by_name["Sayer"] == NodeKind.INTERFACE
    assert by_name["Greeter"] == NodeKind.CLASS
    assert by_name["shout"] == NodeKind.FUNCTION
    assert any(n.kind == NodeKind.METHOD and n.name == "say" for n in nodes)


def test_parse_php_assigns_paths_and_language():
    nodes = PhpHandler().parse(PHP_SRC, "greet.php")
    assert all(n.path == "greet.php" for n in nodes)
    assert all(n.language == "php" for n in nodes)


def test_parse_php_node_ids_have_correct_prefix():
    nodes = PhpHandler().parse(PHP_SRC, "greet.php")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_php_line_numbers_set():
    nodes = PhpHandler().parse(PHP_SRC, "greet.php")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
