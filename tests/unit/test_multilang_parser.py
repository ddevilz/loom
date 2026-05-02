from __future__ import annotations

from pathlib import Path

from loom.core import NodeKind
from loom.ingest.code.languages.java import parse_java
from loom.ingest.code.languages.javascript import parse_javascript
from loom.ingest.code.languages.typescript import parse_typescript


def _by_name(nodes, name: str):
    return [n for n in nodes if n.name == name]


# ── TypeScript ──────────────────────────────────────────────────────


def test_parse_typescript_extracts_class_and_method(tmp_path: Path):
    p = tmp_path / "user.ts"
    p.write_text(
        "class User {\n"
        "  constructor(name: string) {}\n"
        "  getName(): string { return this.name; }\n"
        "}\n",
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    assert len(nodes) >= 2

    user_class = _by_name(nodes, "User")[0]
    assert user_class.kind == NodeKind.CLASS
    assert user_class.language == "typescript"

    get_name = _by_name(nodes, "getName")[0]
    assert get_name.kind == NodeKind.METHOD


def test_parse_typescript_extracts_function(tmp_path: Path):
    p = tmp_path / "utils.ts"
    p.write_text(
        "function hello(name: string): void {\n  console.log(name);\n}\n",
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "hello"
    assert nodes[0].kind == NodeKind.FUNCTION


def test_parse_tsx_file(tmp_path: Path):
    p = tmp_path / "component.tsx"
    p.write_text(
        "function App() {\n  return <div>Hello</div>;\n}\n",
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "App"
    assert nodes[0].language == "tsx"


# ── JavaScript ──────────────────────────────────────────────────────


def test_parse_javascript_extracts_class_and_method(tmp_path: Path):
    p = tmp_path / "app.js"
    p.write_text(
        "class App {\n  start() { console.log('started'); }\n}\n",
        encoding="utf-8",
    )
    nodes = parse_javascript(str(p))
    assert len(nodes) >= 2

    app_class = _by_name(nodes, "App")[0]
    assert app_class.kind == NodeKind.CLASS
    assert app_class.language == "javascript"

    start = _by_name(nodes, "start")[0]
    assert start.kind == NodeKind.METHOD


def test_parse_javascript_extracts_function(tmp_path: Path):
    p = tmp_path / "util.js"
    p.write_text(
        "function add(a, b) {\n  return a + b;\n}\n",
        encoding="utf-8",
    )
    nodes = parse_javascript(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "add"
    assert nodes[0].kind == NodeKind.FUNCTION


def test_parse_javascript_arrow_function(tmp_path: Path):
    p = tmp_path / "arrow.js"
    p.write_text(
        "const multiply = (a, b) => a * b;\n",
        encoding="utf-8",
    )
    nodes = parse_javascript(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "multiply"
    assert nodes[0].kind == NodeKind.FUNCTION
    assert nodes[0].metadata.get("is_arrow") is True


def test_parse_javascript_const_function_expr(tmp_path: Path):
    p = tmp_path / "fn.js"
    p.write_text(
        "const greet = function(name) { return name; };\n",
        encoding="utf-8",
    )
    nodes = parse_javascript(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "greet"
    assert nodes[0].kind == NodeKind.FUNCTION


# ── Fix 5: TypeScript const arrow functions ──────────────────────────


def test_parse_typescript_const_arrow(tmp_path: Path):
    p = tmp_path / "handlers.ts"
    p.write_text(
        "const fetchUsers = async () => { return []; };\n"
        "const add = (a: number, b: number): number => a + b;\n",
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    fetch = _by_name(nodes, "fetchUsers")
    assert len(fetch) == 1
    assert fetch[0].kind == NodeKind.FUNCTION
    assert fetch[0].metadata.get("is_arrow") is True
    assert fetch[0].metadata.get("is_async") is True

    add_fn = _by_name(nodes, "add")
    assert len(add_fn) == 1
    assert add_fn[0].kind == NodeKind.FUNCTION


def test_parse_typescript_export_const_arrow(tmp_path: Path):
    p = tmp_path / "api.ts"
    p.write_text(
        "export const handler = (req: Request) => { return req; };\n",
        encoding="utf-8",
    )
    nodes = parse_typescript(str(p))
    h = _by_name(nodes, "handler")
    assert len(h) == 1
    assert h[0].kind == NodeKind.FUNCTION


# ── Java ────────────────────────────────────────────────────────────


def test_parse_java_extracts_class_and_method(tmp_path: Path):
    p = tmp_path / "User.java"
    p.write_text(
        "public class User {\n  public String getName() {\n    return name;\n  }\n}\n",
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    assert len(nodes) >= 2

    user_class = _by_name(nodes, "User")[0]
    assert user_class.kind == NodeKind.CLASS
    assert user_class.language == "java"

    get_name = _by_name(nodes, "getName")[0]
    assert get_name.kind == NodeKind.METHOD


def test_parse_java_extracts_interface(tmp_path: Path):
    p = tmp_path / "Repository.java"
    p.write_text(
        "public interface Repository {\n  void save();\n}\n",
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    assert len(nodes) >= 1

    repo = _by_name(nodes, "Repository")[0]
    assert repo.kind == NodeKind.INTERFACE


def test_parse_java_extracts_enum(tmp_path: Path):
    p = tmp_path / "Status.java"
    p.write_text(
        "public enum Status {\n  ACTIVE, INACTIVE\n}\n",
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    assert len(nodes) >= 1

    status = _by_name(nodes, "Status")[0]
    assert status.kind == NodeKind.ENUM


def test_parse_java_package_qualified_ids(tmp_path: Path):
    p = tmp_path / "UserService.java"
    p.write_text(
        "package com.example.service;\n\npublic class UserService {\n  public void save() {}\n}\n",
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    cls = _by_name(nodes, "UserService")[0]
    assert "com.example.service.UserService" in cls.id

    method = _by_name(nodes, "save")[0]
    assert "com.example.service.UserService.save" in method.id


def test_parse_java_no_package_still_works(tmp_path: Path):
    p = tmp_path / "Simple.java"
    p.write_text(
        "class Simple {\n  void run() {}\n}\n",
        encoding="utf-8",
    )
    nodes = parse_java(str(p))
    cls = _by_name(nodes, "Simple")[0]
    assert cls.id.endswith(":Simple")

    method = _by_name(nodes, "run")[0]
    assert "Simple.run" in method.id


# ── Registry integration ────────────────────────────────────────────


def test_registry_dispatches_to_correct_parser(tmp_path: Path):
    from loom.analysis.code.parser import parse_code

    # TypeScript
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("function hello() {}", encoding="utf-8")
    ts_nodes = parse_code(str(ts_file))
    assert len(ts_nodes) == 1
    assert ts_nodes[0].language == "typescript"

    # JavaScript
    js_file = tmp_path / "app.js"
    js_file.write_text("function world() {}", encoding="utf-8")
    js_nodes = parse_code(str(js_file))
    assert len(js_nodes) == 1
    assert js_nodes[0].language == "javascript"

    # Java
    java_file = tmp_path / "App.java"
    java_file.write_text("class App {}", encoding="utf-8")
    java_nodes = parse_code(str(java_file))
    assert len(java_nodes) == 1
    assert java_nodes[0].language == "java"
