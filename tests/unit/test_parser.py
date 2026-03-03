from __future__ import annotations

from pathlib import Path

import pytest

from loom.core import NodeKind
from loom.ingest.code.languages.python import parse_python


def _by_name(nodes, name: str):
    return [n for n in nodes if n.name == name]


def test_parse_python_sample_repo_extracts_symbols():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    assert len(nodes) >= 5

    # top-level
    assert _by_name(nodes, "validate_user")
    assert _by_name(nodes, "decorated_function")
    assert _by_name(nodes, "async_login")
    assert _by_name(nodes, "AuthService")

    # nested function
    assert _by_name(nodes, "_normalize")


def test_parse_python_kinds_and_required_fields():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    for n in nodes:
        assert n.kind in {NodeKind.FUNCTION, NodeKind.CLASS, NodeKind.METHOD}
        assert n.path.endswith("tests/fixtures/sample_repo/auth.py")
        assert n.start_line is not None
        assert n.end_line is not None
        assert n.end_line >= n.start_line

        # id must include the start line suffix and correct prefix
        assert n.id.startswith(f"{n.kind.value}:")
        assert n.id.endswith(f":{n.start_line}")


def test_parse_python_methods_include_decorated_method_kinds():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    method_names = {"__init__", "validate", "secret", "from_env", "hash_pw"}
    methods = [n for n in nodes if n.kind == NodeKind.METHOD and n.name in method_names]

    assert {m.name for m in methods} == method_names


def test_parse_python_exclude_tests_option(tmp_path: Path):
    p = tmp_path / "test_sample.py"
    p.write_text(
        "def f():\n    return 1\n",
        encoding="utf-8",
    )

    nodes = parse_python(str(p), exclude_tests=True)
    assert nodes == []


@pytest.mark.parametrize(
    "src",
    [
        "@decorator\ndef f():\n    return 1\n",
        "async def af():\n    return 1\n",
        "def outer():\n    def inner():\n        return 1\n    return inner()\n",
        "class C:\n    @property\n    def p(self):\n        return 1\n",
    ],
)
def test_parse_python_edge_cases(tmp_path: Path, src: str):
    p = tmp_path / "mod.py"
    p.write_text(
        "def decorator(fn):\n    return fn\n\n" + src,
        encoding="utf-8",
    )

    nodes = parse_python(str(p))
    assert nodes


# ── decorator metadata extraction ───────────────────────────────────

def test_decorated_function_has_decorator_metadata():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    dec_fn = _by_name(nodes, "decorated_function")[0]
    assert "decorators" in dec_fn.metadata
    assert "decorator" in dec_fn.metadata["decorators"]


def test_property_method_has_decorator_metadata():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    secret = _by_name(nodes, "secret")[0]
    assert "decorators" in secret.metadata
    assert "property" in secret.metadata["decorators"]


def test_classmethod_staticmethod_have_decorator_metadata():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    from_env = _by_name(nodes, "from_env")[0]
    assert "classmethod" in from_env.metadata["decorators"]

    hash_pw = _by_name(nodes, "hash_pw")[0]
    assert "staticmethod" in hash_pw.metadata["decorators"]


def test_plain_function_has_no_decorator_metadata():
    path = "tests/fixtures/sample_repo/auth.py"
    nodes = parse_python(path)

    validate = _by_name(nodes, "validate_user")[0]
    assert "decorators" not in validate.metadata


# ── framework hints ─────────────────────────────────────────────────

def test_flask_route_gets_framework_hint():
    path = "tests/fixtures/sample_repo/flask_app.py"
    nodes = parse_python(path)

    login = _by_name(nodes, "login")[0]
    assert login.metadata.get("framework_hint") == "flask_route"

    logout = _by_name(nodes, "logout")[0]
    assert logout.metadata.get("framework_hint") == "flask_route"

    helper = _by_name(nodes, "helper")[0]
    assert "framework_hint" not in helper.metadata


def test_fastapi_route_hint(tmp_path: Path):
    p = tmp_path / "api.py"
    p.write_text(
        "class app:\n    @staticmethod\n    def get(path):\n        def w(fn): return fn\n        return w\n\n"
        "@app.get('/users')\ndef list_users():\n    return []\n",
        encoding="utf-8",
    )
    nodes = parse_python(str(p))
    lu = _by_name(nodes, "list_users")[0]
    assert lu.metadata.get("framework_hint") == "fastapi_route"


# ── registry + parse_code file filtering ────────────────────────────

def test_parse_code_skips_unsupported_extensions(tmp_path: Path):
    from loom.analysis.code.parser import parse_code

    # Only truly unsupported extensions (images, fonts, archives, etc.)
    for ext in [".svg", ".png", ".pdf", ".zip", ".woff"]:
        p = tmp_path / f"file{ext}"
        p.write_text("binary data", encoding="utf-8")
        assert parse_code(str(p)) == []


def test_parse_code_parses_python(tmp_path: Path):
    from loom.analysis.code.parser import parse_code

    p = tmp_path / "mod.py"
    p.write_text("def hello():\n    pass\n", encoding="utf-8")
    nodes = parse_code(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "hello"


# ── parse_tree directory walker ─────────────────────────────────────

def test_parse_tree_walks_directory(tmp_path: Path):
    from loom.analysis.code.parser import parse_tree

    # create a mini project
    (tmp_path / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    # markup files are now parsed as FILE nodes
    (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")

    nodes = parse_tree(str(tmp_path))
    names = {n.name for n in nodes}
    assert "main" in names
    assert "helper" in names
    # 2 functions + 3 FILE nodes (html, css, json)
    assert len(nodes) == 5
    
    # Verify we have both code and file nodes
    kinds = {n.kind for n in nodes}
    assert NodeKind.FUNCTION in kinds
    assert NodeKind.FILE in kinds


def test_parse_tree_skips_venv_and_node_modules(tmp_path: Path):
    from loom.analysis.code.parser import parse_tree

    # real code
    (tmp_path / "app.py").write_text("def real():\n    pass\n", encoding="utf-8")

    # code inside dirs that should be skipped
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "dep.py").write_text("def vendored():\n    pass\n", encoding="utf-8")

    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.py").write_text("def npm():\n    pass\n", encoding="utf-8")

    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "mod.py").write_text("def cached():\n    pass\n", encoding="utf-8")

    nodes = parse_tree(str(tmp_path))
    names = {n.name for n in nodes}
    assert names == {"real"}


def test_parse_tree_skips_hidden_dirs(tmp_path: Path):
    from loom.analysis.code.parser import parse_tree

    (tmp_path / "app.py").write_text("def real():\n    pass\n", encoding="utf-8")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "x.py").write_text("def hidden():\n    pass\n", encoding="utf-8")

    nodes = parse_tree(str(tmp_path))
    names = {n.name for n in nodes}
    assert names == {"real"}
