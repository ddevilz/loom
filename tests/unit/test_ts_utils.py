import tree_sitter_python as ts_py
from tree_sitter import Language, Parser

from loom.indexer.languages._ts_utils import (
    count_node_type,
    has_decorator,
    has_decorator_prefix,
    walk_all,
)

PY_LANG = Language(ts_py.language())


def _parse(src: str):
    p = Parser(PY_LANG)
    return p.parse(src.encode("utf-8")).root_node


def test_walk_all_yields_all_descendants():
    root = _parse("def f():\n    if x:\n        return 1\n")
    types = [n.type for n in walk_all(root)]
    assert "function_definition" in types
    assert "if_statement" in types
    assert "return_statement" in types


def test_count_node_type_counts_correctly():
    root = _parse(
        "def f():\n"
        "    try:\n        a\n    except: pass\n"
        "    try:\n        b\n    except: pass\n"
        "    try:\n        c\n    except: pass\n"
    )
    assert count_node_type(root, "try_statement") == 3


def test_has_decorator_detects_match():
    root = _parse("@dataclass\nclass C: pass\n")
    cls = next(n for n in walk_all(root) if n.type == "decorated_definition")
    assert has_decorator(cls, "dataclass") is True
    assert has_decorator(cls, "frozen") is False


def test_has_decorator_prefix():
    root = _parse("@app.route('/x')\ndef view(): pass\n")
    fn = next(n for n in walk_all(root) if n.type == "decorated_definition")
    assert has_decorator_prefix(fn, ("app.route",)) is True
    assert has_decorator_prefix(fn, ("celery.task",)) is False
