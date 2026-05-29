import tree_sitter_go as ts_go
import tree_sitter_rust as ts_rust
import tree_sitter_kotlin as ts_kotlin
from tree_sitter import Language, Parser

from loom.indexer.language_notes import extract_language_notes


def _parse(src: bytes, lang_mod):
    L = Language(lang_mod.language())
    return Parser(L).parse(src).root_node


def _first(node, type_name):
    if node.type == type_name:
        return node
    for c in node.children:
        r = _first(c, type_name)
        if r is not None:
            return r
    return None


def test_go_goroutine_detected():
    src = b"package main\nfunc work() { go doIt() }\n"
    root = _parse(src, ts_go)
    fn = _first(root, "function_declaration")
    notes = extract_language_notes(fn, "go", src)
    assert notes is not None and "goroutine" in notes


def test_rust_async_detected():
    src = b"async fn fetch() -> u32 { 0 }\n"
    root = _parse(src, ts_rust)
    fn = _first(root, "function_item")
    notes = extract_language_notes(fn, "rust", src)
    assert notes is not None and "async" in notes


def test_kotlin_suspend_detected():
    src = b"suspend fun fetch(): Int = 0\n"
    root = _parse(src, ts_kotlin)
    fn = _first(root, "function_declaration")
    notes = extract_language_notes(fn, "kotlin", src)
    assert notes is not None and "suspend" in notes
