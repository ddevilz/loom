from __future__ import annotations

from pathlib import Path

from loom.core import NodeKind
from loom.ingest.code.languages.markup import (
    parse_css,
    parse_html,
    parse_json,
    parse_xml,
    parse_yaml,
)


# ── HTML parsing ────────────────────────────────────────────────────

def test_parse_html_extracts_title(tmp_path: Path):
    p = tmp_path / "index.html"
    p.write_text(
        "<html><head><title>Login Page</title></head><body></body></html>",
        encoding="utf-8",
    )
    nodes = parse_html(str(p))
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.FILE
    assert nodes[0].language == "html"
    assert nodes[0].metadata["title"] == "Login Page"


def test_parse_html_detects_forms(tmp_path: Path):
    p = tmp_path / "form.html"
    p.write_text(
        '<form action="/login" method="post"><input name="user"></form>'
        '<form action="/signup"><input name="email"></form>',
        encoding="utf-8",
    )
    nodes = parse_html(str(p))
    assert nodes[0].metadata["form_count"] == 2
    assert "/login" in nodes[0].metadata["form_actions"]
    assert "/signup" in nodes[0].metadata["form_actions"]


def test_parse_html_detects_jinja2_template(tmp_path: Path):
    p = tmp_path / "template.html"
    p.write_text(
        "<html>{{ user.name }} {% if logged_in %}Welcome{% endif %}</html>",
        encoding="utf-8",
    )
    nodes = parse_html(str(p))
    assert nodes[0].metadata.get("template_engine") == "jinja2"


def test_parse_html_extracts_scripts_and_styles(tmp_path: Path):
    p = tmp_path / "page.html"
    p.write_text(
        '<html><head>'
        '<link rel="stylesheet" href="/static/main.css">'
        '<script src="/static/app.js"></script>'
        '</head></html>',
        encoding="utf-8",
    )
    nodes = parse_html(str(p))
    assert "/static/app.js" in nodes[0].metadata["scripts"]
    assert "/static/main.css" in nodes[0].metadata["stylesheets"]


# ── XML parsing ─────────────────────────────────────────────────────

def test_parse_xml_extracts_root_tag(tmp_path: Path):
    p = tmp_path / "config.xml"
    p.write_text(
        '<?xml version="1.0"?><configuration><setting>value</setting></configuration>',
        encoding="utf-8",
    )
    nodes = parse_xml(str(p))
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.FILE
    assert nodes[0].language == "xml"
    assert nodes[0].metadata["root_tag"] == "configuration"
    assert nodes[0].metadata.get("config_type") == "application_config"


def test_parse_xml_counts_elements(tmp_path: Path):
    p = tmp_path / "data.xml"
    p.write_text(
        "<root><item>1</item><item>2</item><item>3</item></root>",
        encoding="utf-8",
    )
    nodes = parse_xml(str(p))
    assert nodes[0].metadata["element_count"] >= 4  # root + 3 items


def test_parse_xml_handles_invalid_xml(tmp_path: Path):
    p = tmp_path / "bad.xml"
    p.write_text("<root><unclosed>", encoding="utf-8")
    nodes = parse_xml(str(p))
    assert nodes[0].metadata.get("parse_error") is True


# ── JSON parsing ────────────────────────────────────────────────────

def test_parse_json_extracts_top_level_keys(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text('{"name": "test", "version": "1.0", "author": "dev"}', encoding="utf-8")
    nodes = parse_json(str(p))
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.FILE
    assert nodes[0].language == "json"
    assert set(nodes[0].metadata["top_level_keys"]) == {"name", "version", "author"}


def test_parse_json_detects_package_json(tmp_path: Path):
    p = tmp_path / "package.json"
    p.write_text(
        '{"name": "myapp", "version": "1.0.0", "dependencies": {"express": "^4.0.0"}}',
        encoding="utf-8",
    )
    nodes = parse_json(str(p))
    assert nodes[0].metadata.get("file_type") == "package.json"


def test_parse_json_detects_json_schema(tmp_path: Path):
    p = tmp_path / "schema.json"
    p.write_text(
        '{"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}',
        encoding="utf-8",
    )
    nodes = parse_json(str(p))
    assert nodes[0].metadata.get("file_type") == "json_schema"


def test_parse_json_handles_array(tmp_path: Path):
    p = tmp_path / "list.json"
    p.write_text('[{"id": 1}, {"id": 2}, {"id": 3}]', encoding="utf-8")
    nodes = parse_json(str(p))
    assert nodes[0].metadata.get("is_array") is True
    assert nodes[0].metadata.get("item_count") == 3


def test_parse_json_handles_invalid_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text('{"unclosed": ', encoding="utf-8")
    nodes = parse_json(str(p))
    assert nodes[0].metadata.get("parse_error") is True


# ── CSS parsing ─────────────────────────────────────────────────────

def test_parse_css_extracts_classes(tmp_path: Path):
    p = tmp_path / "style.css"
    p.write_text(
        ".btn { color: red; }\n.btn-primary { background: blue; }\n#main { width: 100%; }",
        encoding="utf-8",
    )
    nodes = parse_css(str(p))
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.FILE
    assert nodes[0].language == "css"
    assert nodes[0].metadata["class_count"] == 2
    assert "btn" in nodes[0].metadata["classes"]
    assert "btn-primary" in nodes[0].metadata["classes"]
    assert nodes[0].metadata["id_count"] == 1


def test_parse_css_detects_media_queries(tmp_path: Path):
    p = tmp_path / "responsive.css"
    p.write_text(
        "@media (max-width: 768px) { .mobile { display: block; } }\n"
        "@media print { .no-print { display: none; } }",
        encoding="utf-8",
    )
    nodes = parse_css(str(p))
    assert nodes[0].metadata["media_query_count"] == 2


def test_parse_css_extracts_css_variables(tmp_path: Path):
    p = tmp_path / "vars.css"
    p.write_text(
        ":root { --primary-color: #007bff; --font-size: 16px; }",
        encoding="utf-8",
    )
    nodes = parse_css(str(p))
    assert "primary-color" in nodes[0].metadata["css_variables"]
    assert "font-size" in nodes[0].metadata["css_variables"]


# ── YAML parsing ────────────────────────────────────────────────────

def test_parse_yaml_extracts_top_level_keys(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("name: myapp\nversion: 1.0\nport: 8080\n", encoding="utf-8")
    nodes = parse_yaml(str(p))
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.FILE
    assert nodes[0].language == "yaml"
    assert set(nodes[0].metadata["top_level_keys"]) == {"name", "version", "port"}


def test_parse_yaml_detects_docker_compose(tmp_path: Path):
    p = tmp_path / "docker-compose.yml"
    p.write_text(
        "version: '3.8'\nservices:\n  web:\n    image: nginx\n",
        encoding="utf-8",
    )
    nodes = parse_yaml(str(p))
    assert nodes[0].metadata.get("file_type") == "docker-compose"


def test_parse_yaml_detects_kubernetes(tmp_path: Path):
    p = tmp_path / "deployment.yaml"
    p.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: myapp\n",
        encoding="utf-8",
    )
    nodes = parse_yaml(str(p))
    assert nodes[0].metadata.get("file_type") == "kubernetes"


def test_parse_yaml_detects_github_actions(tmp_path: Path):
    p = tmp_path / "ci.yml"
    p.write_text(
        "name: CI\non:\n  push:\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    nodes = parse_yaml(str(p))
    assert nodes[0].metadata.get("file_type") == "github_actions"


# ── Integration with parse_tree ─────────────────────────────────────

def test_parse_tree_includes_markup_files(tmp_path: Path):
    from loom.analysis.code.parser import parse_tree

    # Create a mini web project
    (tmp_path / "app.py").write_text("def index():\n    pass\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html><title>Home</title></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text(".btn { color: red; }", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"debug": true}', encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("version: '3'\nservices:\n  web:\n", encoding="utf-8")

    nodes = parse_tree(str(tmp_path))
    
    # Should have: 1 function + 4 FILE nodes
    assert len(nodes) == 5
    
    kinds = {n.kind for n in nodes}
    assert NodeKind.FUNCTION in kinds
    assert NodeKind.FILE in kinds
    
    languages = {n.language for n in nodes if n.language}
    assert languages == {"python", "html", "css", "json", "yaml"}
