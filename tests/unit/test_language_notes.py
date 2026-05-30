import tree_sitter_python as ts_py
from tree_sitter import Language, Parser

from loom.indexer.language_notes import extract_language_notes
from loom.indexer.languages._ts_utils import walk_all

PY_LANG = Language(ts_py.language())


def _parse_py(src: str):
    return Parser(PY_LANG).parse(src.encode("utf-8")).root_node


def _func(src: str):
    root = _parse_py(src)
    for n in walk_all(root):
        if n.type == "function_definition":
            return n
    raise AssertionError("no function found")


def test_python_async_generator():
    fn = _func("async def stream():\n    yield 1\n")
    src = b"async def stream():\n    yield 1\n"
    notes = extract_language_notes(fn, "python", src)
    assert notes is not None and "async generator" in notes


def test_python_async_function():
    src = b"async def f():\n    return 1\n"
    fn = _func(src.decode())
    notes = extract_language_notes(fn, "python", src)
    assert notes is not None and "async function" in notes


def test_python_flask_route():
    src = b"@app.route('/x')\ndef view():\n    return 'x'\n"
    root = _parse_py(src.decode())
    # decorated_definition wraps function_definition in Python grammar
    decorated = next(n for n in walk_all(root) if n.type == "decorated_definition")
    notes = extract_language_notes(decorated, "python", src)
    assert notes is not None and "Flask/FastAPI route" in notes


def test_python_no_match_returns_none():
    src = b"def plain():\n    return 1\n"
    fn = _func(src.decode())
    notes = extract_language_notes(fn, "python", src)
    assert notes is None
