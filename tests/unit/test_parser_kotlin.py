"""Unit tests for the Kotlin structural parser."""

from __future__ import annotations

from loom.graph.models import NodeKind
from loom.indexer.languages.kotlin import KotlinHandler

KT_SRC = b"""package com.example

class Greeter(val name: String) {
    fun greet(): String = "hi $name"
}

object Singleton {
    fun ping() = "pong"
}

fun main() {
    println(Greeter("x").greet())
}
"""


def test_parse_kotlin_basic():
    nodes = KotlinHandler().parse(KT_SRC, "Main.kt")
    by_name = {n.name: n.kind for n in nodes}
    assert by_name["Greeter"] == NodeKind.CLASS
    assert by_name["Singleton"] == NodeKind.CLASS
    assert by_name["main"] == NodeKind.FUNCTION
    assert any(n.kind == NodeKind.METHOD and n.name == "greet" for n in nodes)


def test_parse_kotlin_assigns_paths_and_language():
    nodes = KotlinHandler().parse(KT_SRC, "Main.kt")
    assert all(n.path == "Main.kt" for n in nodes)
    assert all(n.language == "kotlin" for n in nodes)


def test_parse_kotlin_node_ids_have_correct_prefix():
    nodes = KotlinHandler().parse(KT_SRC, "Main.kt")
    for n in nodes:
        assert n.id.startswith(f"{n.kind.value}:")


def test_parse_kotlin_line_numbers_set():
    nodes = KotlinHandler().parse(KT_SRC, "Main.kt")
    for n in nodes:
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line
