from __future__ import annotations

from pathlib import Path

from loom.core import NodeKind
from loom.ingest.code.languages.go_lang import parse_go
from loom.ingest.code.languages.java import parse_java
from loom.ingest.code.languages.javascript import parse_javascript
from loom.ingest.code.languages.ruby import parse_ruby
from loom.ingest.code.languages.rust import parse_rust
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


# ── Go ──────────────────────────────────────────────────────────────


def test_parse_go_extracts_function(tmp_path: Path):
    p = tmp_path / "main.go"
    p.write_text(
        'package main\n\nfunc main() {\n  println("hello")\n}\n',
        encoding="utf-8",
    )
    nodes = parse_go(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "main"
    assert nodes[0].kind == NodeKind.FUNCTION
    assert nodes[0].language == "go"


def test_parse_go_extracts_struct(tmp_path: Path):
    p = tmp_path / "user.go"
    p.write_text(
        "package main\n\ntype User struct {\n  Name string\n}\n",
        encoding="utf-8",
    )
    nodes = parse_go(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "User"
    assert nodes[0].kind == NodeKind.CLASS


def test_parse_go_extracts_method_with_receiver(tmp_path: Path):
    p = tmp_path / "user.go"
    p.write_text(
        "package main\n\n"
        "type User struct {}\n\n"
        "func (u *User) GetName() string {\n"
        "  return u.Name\n"
        "}\n",
        encoding="utf-8",
    )
    nodes = parse_go(str(p))

    get_name = _by_name(nodes, "GetName")[0]
    assert get_name.kind == NodeKind.METHOD
    assert "receiver" in get_name.metadata
    assert get_name.metadata["receiver"] == "User"


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
        "package com.example.service;\n\n"
        "public class UserService {\n"
        "  public void save() {}\n"
        "}\n",
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


# ── Rust ────────────────────────────────────────────────────────────


def test_parse_rust_extracts_function(tmp_path: Path):
    p = tmp_path / "main.rs"
    p.write_text(
        'fn main() {\n  println!("hello");\n}\n',
        encoding="utf-8",
    )
    nodes = parse_rust(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "main"
    assert nodes[0].kind == NodeKind.FUNCTION
    assert nodes[0].language == "rust"


def test_parse_rust_extracts_struct(tmp_path: Path):
    p = tmp_path / "user.rs"
    p.write_text(
        "struct User {\n  name: String,\n}\n",
        encoding="utf-8",
    )
    nodes = parse_rust(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "User"
    assert nodes[0].kind == NodeKind.CLASS


def test_parse_rust_extracts_impl_methods(tmp_path: Path):
    p = tmp_path / "user.rs"
    p.write_text(
        "struct User {}\n\n"
        "impl User {\n"
        "  fn new() -> Self {\n"
        "    User {}\n"
        "  }\n"
        "  fn get_name(&self) -> &str {\n"
        "    &self.name\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    nodes = parse_rust(str(p))

    # Should have: User struct + 2 methods
    assert len(nodes) >= 3

    new_method = _by_name(nodes, "new")[0]
    assert new_method.kind == NodeKind.METHOD
    assert "impl_type" in new_method.metadata

    get_name = _by_name(nodes, "get_name")[0]
    assert get_name.kind == NodeKind.METHOD


# ── Ruby ────────────────────────────────────────────────────────────


def test_parse_ruby_extracts_class_and_method(tmp_path: Path):
    p = tmp_path / "user.rb"
    p.write_text(
        "class User\n"
        "  def initialize(name)\n"
        "    @name = name\n"
        "  end\n"
        "  def get_name\n"
        "    @name\n"
        "  end\n"
        "end\n",
        encoding="utf-8",
    )
    nodes = parse_ruby(str(p))
    assert len(nodes) >= 3

    user_class = _by_name(nodes, "User")[0]
    assert user_class.kind == NodeKind.CLASS
    assert user_class.language == "ruby"

    init = _by_name(nodes, "initialize")[0]
    assert init.kind == NodeKind.METHOD


def test_parse_ruby_extracts_module(tmp_path: Path):
    p = tmp_path / "utils.rb"
    p.write_text(
        "module Utils\n  def self.helper\n    'help'\n  end\nend\n",
        encoding="utf-8",
    )
    nodes = parse_ruby(str(p))
    assert len(nodes) >= 1

    utils = _by_name(nodes, "Utils")[0]
    assert utils.kind == NodeKind.CLASS


def test_parse_ruby_extracts_top_level_function(tmp_path: Path):
    p = tmp_path / "script.rb"
    p.write_text(
        'def greet(name)\n  puts "Hello, #{name}"\nend\n',
        encoding="utf-8",
    )
    nodes = parse_ruby(str(p))
    assert len(nodes) == 1
    assert nodes[0].name == "greet"
    assert nodes[0].kind == NodeKind.FUNCTION


def test_parse_ruby_rails_dsl_extraction(tmp_path: Path):
    p = tmp_path / "user.rb"
    p.write_text(
        "class User < ApplicationRecord\n"
        "  has_many :posts\n"
        "  belongs_to :team\n"
        "  validates :name, presence: true\n"
        "  scope :active, -> { where(active: true) }\n"
        "  before_action :authenticate\n"
        "\n"
        "  def save\n"
        "    true\n"
        "  end\n"
        "end\n",
        encoding="utf-8",
    )
    nodes = parse_ruby(str(p))
    user = _by_name(nodes, "User")[0]
    assert user.kind == NodeKind.CLASS
    assert user.metadata.get("extends") == "ApplicationRecord"

    dsl = user.metadata.get("rails_dsl")
    assert dsl is not None
    dsl_methods = [d["method"] for d in dsl]
    assert "has_many" in dsl_methods
    assert "belongs_to" in dsl_methods
    assert "validates" in dsl_methods
    assert "scope" in dsl_methods
    assert "before_action" in dsl_methods

    # Method still extracted
    save = _by_name(nodes, "save")
    assert len(save) == 1
    assert save[0].kind == NodeKind.METHOD


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

    # Go
    go_file = tmp_path / "main.go"
    go_file.write_text("package main\nfunc main() {}", encoding="utf-8")
    go_nodes = parse_code(str(go_file))
    assert len(go_nodes) == 1
    assert go_nodes[0].language == "go"

    # Java
    java_file = tmp_path / "App.java"
    java_file.write_text("class App {}", encoding="utf-8")
    java_nodes = parse_code(str(java_file))
    assert len(java_nodes) == 1
    assert java_nodes[0].language == "java"

    # Rust
    rust_file = tmp_path / "main.rs"
    rust_file.write_text("fn main() {}", encoding="utf-8")
    rust_nodes = parse_code(str(rust_file))
    assert len(rust_nodes) == 1
    assert rust_nodes[0].language == "rust"

    # Ruby
    ruby_file = tmp_path / "app.rb"
    ruby_file.write_text("def hello; end", encoding="utf-8")
    ruby_nodes = parse_code(str(ruby_file))
    assert len(ruby_nodes) == 1
    assert ruby_nodes[0].language == "ruby"
