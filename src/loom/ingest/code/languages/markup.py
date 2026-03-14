from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from loom.core import Node, NodeKind, NodeSource
from loom.core.content_hash import content_hash_bytes
from loom.ingest.code.languages.constants import (
    FILETYPE_APPLICATION_CONFIG,
    FILETYPE_DOCKER_COMPOSE,
    FILETYPE_GITHUB_ACTIONS,
    FILETYPE_GITLAB_CI,
    FILETYPE_JSON_SCHEMA,
    FILETYPE_KUBERNETES,
    FILETYPE_MAVEN_POM,
    FILETYPE_NPM_PACKAGE,
    FILETYPE_OPENAPI_SPEC,
    FILETYPE_PACKAGE_JSON,
    FILETYPE_PROJECT_FILE,
    FILETYPE_TSCONFIG,
    GITLAB_CI_FILENAMES,
    JSON_KEY_COMPILER_OPTIONS,
    JSON_KEY_DEPENDENCIES,
    JSON_KEY_NAME,
    JSON_KEY_OPENAPI,
    JSON_KEY_SCHEMA,
    JSON_KEY_SCRIPTS,
    JSON_KEY_SWAGGER,
    JSON_KEY_VERSION,
    LANG_CSS,
    LANG_ENV,
    LANG_HTML,
    LANG_INI,
    LANG_JSON,
    LANG_PROPERTIES,
    LANG_TOML,
    LANG_XML,
    LANG_YAML,
    META_CLASS_COUNT,
    META_CLASSES,
    META_CONFIG_TYPE,
    META_CSS_VARIABLES,
    META_DATABASE_CONFIG,
    META_DEPENDENCIES,
    META_DEV_DEPENDENCIES,
    META_ELEMENT_COUNT,
    META_FILE_TYPE,
    META_FORM_ACTIONS,
    META_FORM_COUNT,
    META_ID_COUNT,
    META_IS_ARRAY,
    META_ITEM_COUNT,
    META_MEDIA_QUERY_COUNT,
    META_NAMESPACES,
    META_PARSE_ERROR,
    META_PROJECT_NAME,
    META_PROJECT_VERSION,
    META_PROPERTY_COUNT,
    META_PROPERTY_KEYS,
    META_ROOT_TAG,
    META_SCHEMA_URL,
    META_SCRIPTS,
    META_SENSITIVE_KEYS,
    META_SPRING_PROFILE,
    META_STYLESHEETS,
    META_TEMPLATE_ENGINE,
    META_TITLE,
    META_TOP_LEVEL_KEYS,
    META_VARIABLE_COUNT,
    META_VARIABLE_NAMES,
    RX_CSS_CLASS,
    RX_CSS_ID,
    RX_CSS_MEDIA,
    RX_CSS_VAR,
    RX_HTML_ACTION,
    RX_HTML_CSS_HREF,
    RX_HTML_FORM,
    RX_HTML_SCRIPT_SRC,
    RX_HTML_TITLE,
    RX_YAML_TOP_KEY,
    TEMPLATE_EJS,
    TEMPLATE_JINJA2,
    TEMPLATE_PHP,
    YAML_KEY_API_VERSION,
    YAML_KEY_JOBS,
    YAML_KEY_KIND,
    YAML_KEY_NAME,
    YAML_KEY_ON,
    YAML_KEY_SERVICES,
    YAML_KEY_VERSION,
)


def parse_html(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from HTML files: title, forms, script tags, template variables."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    # Extract title
    title_match = re.search(RX_HTML_TITLE, content, re.IGNORECASE | re.DOTALL)
    if title_match:
        meta[META_TITLE] = title_match.group(1).strip()

    # Count forms
    forms = re.findall(RX_HTML_FORM, content, re.IGNORECASE)
    if forms:
        meta[META_FORM_COUNT] = len(forms)
        # Extract form actions
        actions = [
            m.group(1) for m in re.finditer(RX_HTML_ACTION, content, re.IGNORECASE)
        ]
        if actions:
            meta[META_FORM_ACTIONS] = actions

    # Detect template engine syntax
    template_hints = []
    if "{{" in content or "{%" in content:
        template_hints.append(TEMPLATE_JINJA2)
    if "<%=" in content or "<%%" in content:
        template_hints.append(TEMPLATE_EJS)
    if "<?php" in content:
        template_hints.append(TEMPLATE_PHP)
    if template_hints:
        meta[META_TEMPLATE_ENGINE] = template_hints[0]

    # Extract script src references
    scripts = re.findall(RX_HTML_SCRIPT_SRC, content, re.IGNORECASE)
    if scripts:
        meta[META_SCRIPTS] = scripts[:10]

    # Extract CSS href references
    styles = re.findall(RX_HTML_CSS_HREF, content, re.IGNORECASE)
    if styles:
        meta[META_STYLESHEETS] = styles[:10]

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_HTML,
        metadata=meta,
    )
    return [node]


def parse_xml(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from XML files: root tag, namespaces, key attributes."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    try:
        tree = ET.fromstring(content)
    except ET.ParseError:
        meta[META_PARSE_ERROR] = True
        # Create a minimal tree for basic metadata
        tree = ET.Element("root")

    meta[META_ROOT_TAG] = tree.tag

    # Extract namespaces from parsed tree
    namespaces = {}
    for elem in tree.iter():
        if elem.tag.startswith("{"):
            ns_end = elem.tag.find("}")
            if ns_end > 0:
                ns_uri = elem.tag[1:ns_end]
                if ns_uri not in namespaces.values():
                    namespaces[f"ns{len(namespaces)}"] = ns_uri
    if namespaces:
        meta[META_NAMESPACES] = namespaces

    # Count child elements
    meta[META_ELEMENT_COUNT] = len(list(tree.iter()))

    # Extract common config patterns
    if tree.tag in {"configuration", "config", "settings"}:
        meta[META_CONFIG_TYPE] = FILETYPE_APPLICATION_CONFIG
    elif "pom" in tree.tag.lower():
        meta[META_CONFIG_TYPE] = FILETYPE_MAVEN_POM
    elif tree.tag == "project":
        meta[META_CONFIG_TYPE] = FILETYPE_PROJECT_FILE

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_XML,
        metadata=meta,
    )
    return [node]


def parse_json(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from JSON files: schema hints, top-level keys."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    data = json.loads(content)

    if isinstance(data, dict):
        meta[META_TOP_LEVEL_KEYS] = list(data.keys())[:20]

        # Detect common JSON file types
        if JSON_KEY_NAME in data and JSON_KEY_VERSION in data:
            if JSON_KEY_DEPENDENCIES in data:
                meta[META_FILE_TYPE] = FILETYPE_PACKAGE_JSON
            elif JSON_KEY_SCRIPTS in data:
                meta[META_FILE_TYPE] = FILETYPE_NPM_PACKAGE

        if JSON_KEY_SCHEMA in data:
            meta[META_FILE_TYPE] = FILETYPE_JSON_SCHEMA
            meta[META_SCHEMA_URL] = data[JSON_KEY_SCHEMA]

        if JSON_KEY_OPENAPI in data or JSON_KEY_SWAGGER in data:
            meta[META_FILE_TYPE] = FILETYPE_OPENAPI_SPEC

        if JSON_KEY_COMPILER_OPTIONS in data:
            meta[META_FILE_TYPE] = FILETYPE_TSCONFIG

    elif isinstance(data, list):
        meta[META_IS_ARRAY] = True
        meta[META_ITEM_COUNT] = len(data)

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_JSON,
        metadata=meta,
    )
    return [node]


def parse_css(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from CSS files: selector count, class names, media queries."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    # Extract class selectors
    classes = re.findall(RX_CSS_CLASS, content)
    if classes:
        meta[META_CLASS_COUNT] = len(classes)
        meta[META_CLASSES] = list(set(classes))[:50]

    # Extract ID selectors
    ids = re.findall(RX_CSS_ID, content)
    if ids:
        meta[META_ID_COUNT] = len(ids)

    # Detect media queries
    media_queries = re.findall(RX_CSS_MEDIA, content)
    if media_queries:
        meta[META_MEDIA_QUERY_COUNT] = len(media_queries)

    # Detect CSS variables
    css_vars = re.findall(RX_CSS_VAR, content)
    if css_vars:
        meta[META_CSS_VARIABLES] = list(set(css_vars))[:20]

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_CSS,
        metadata=meta,
    )
    return [node]


def parse_yaml(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from YAML files: top-level keys, detect config type."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    # Simple YAML key extraction (not full parse to avoid dependency)
    # Extract top-level keys (lines that start with word: at beginning)
    top_keys = re.findall(RX_YAML_TOP_KEY, content, re.MULTILINE)
    if top_keys:
        meta[META_TOP_LEVEL_KEYS] = list(set(top_keys))[:20]

    # Detect common YAML config types
    if YAML_KEY_VERSION in content and YAML_KEY_SERVICES in content:
        meta[META_FILE_TYPE] = FILETYPE_DOCKER_COMPOSE
    elif YAML_KEY_API_VERSION in content and YAML_KEY_KIND in content:
        meta[META_FILE_TYPE] = FILETYPE_KUBERNETES
    elif (
        YAML_KEY_NAME in content and YAML_KEY_ON in content and YAML_KEY_JOBS in content
    ):
        meta[META_FILE_TYPE] = FILETYPE_GITHUB_ACTIONS
    elif p.name in GITLAB_CI_FILENAMES:
        meta[META_FILE_TYPE] = FILETYPE_GITLAB_CI

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_YAML,
        metadata=meta,
    )
    return [node]


def _parse_kv_file(content: str, *, skip_bang_comments: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if skip_bang_comments and line.startswith("!"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def parse_properties(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from Java .properties files: keys, Spring profiles, database config."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    properties = _parse_kv_file(content, skip_bang_comments=True)

    if properties:
        meta[META_PROPERTY_COUNT] = len(properties)
        meta[META_PROPERTY_KEYS] = list(properties.keys())[:50]

        # Detect Spring profile
        if "spring.profiles.active" in properties:
            meta[META_SPRING_PROFILE] = properties["spring.profiles.active"]

        # Detect database configuration
        db_keys = [
            k
            for k in properties
            if "database" in k.lower()
            or "datasource" in k.lower()
            or "jdbc" in k.lower()
        ]
        if db_keys:
            meta[META_DATABASE_CONFIG] = True

        # Detect sensitive keys
        sensitive_patterns = ["password", "secret", "key", "token", "credential"]
        sensitive = [
            k
            for k in properties
            if any(pattern in k.lower() for pattern in sensitive_patterns)
        ]
        if sensitive:
            meta[META_SENSITIVE_KEYS] = sensitive[:10]

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_PROPERTIES,
        metadata=meta,
    )
    return [node]


def parse_env(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from .env files: environment variables, sensitive keys."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    variables = _parse_kv_file(content)

    if variables:
        meta[META_VARIABLE_COUNT] = len(variables)
        meta[META_VARIABLE_NAMES] = list(variables.keys())[:50]

        # Detect sensitive keys
        sensitive_patterns = [
            "password",
            "secret",
            "key",
            "token",
            "credential",
            "api_key",
            "private",
        ]
        sensitive = [
            k
            for k in variables
            if any(pattern in k.lower() for pattern in sensitive_patterns)
        ]
        if sensitive:
            meta[META_SENSITIVE_KEYS] = sensitive[:10]

        # Detect database configuration
        db_keys = [
            k for k in variables if "database" in k.lower() or "db_" in k.lower()
        ]
        if db_keys:
            meta[META_DATABASE_CONFIG] = True

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_ENV,
        metadata=meta,
    )
    return [node]


def parse_toml(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from TOML files: dependencies, project info."""
    p = Path(path)
    src = p.read_bytes()

    meta: dict[str, Any] = {}
    dependencies: list[str] = []
    dev_dependencies: list[str] = []

    data = tomllib.loads(src.decode("utf-8", errors="replace"))

    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        version = project.get("version")
        if isinstance(name, str) and name:
            meta[META_PROJECT_NAME] = name
        if isinstance(version, str) and version:
            meta[META_PROJECT_VERSION] = version
        project_dependencies = project.get("dependencies")
        if isinstance(project_dependencies, list):
            dependencies.extend(
                dep.split()[0]
                for dep in project_dependencies
                if isinstance(dep, str) and dep.strip()
            )

    tool = data.get("tool")
    if isinstance(tool, dict):
        poetry = tool.get("poetry")
        if isinstance(poetry, dict):
            name = poetry.get("name")
            version = poetry.get("version")
            if isinstance(name, str) and name and META_PROJECT_NAME not in meta:
                meta[META_PROJECT_NAME] = name
            if (
                isinstance(version, str)
                and version
                and META_PROJECT_VERSION not in meta
            ):
                meta[META_PROJECT_VERSION] = version

            poetry_dependencies = poetry.get("dependencies")
            if isinstance(poetry_dependencies, dict):
                dependencies.extend(
                    key
                    for key in poetry_dependencies
                    if isinstance(key, str) and key != "python"
                )

            poetry_group = poetry.get("group")
            if isinstance(poetry_group, dict):
                for group in poetry_group.values():
                    if not isinstance(group, dict):
                        continue
                    group_dependencies = group.get("dependencies")
                    if isinstance(group_dependencies, dict):
                        dev_dependencies.extend(
                            key for key in group_dependencies if isinstance(key, str)
                        )

        pdm = tool.get("pdm")
        if isinstance(pdm, dict):
            dev_deps = pdm.get("dev-dependencies")
            if isinstance(dev_deps, dict):
                for dep_group in dev_deps.values():
                    if isinstance(dep_group, list):
                        dev_dependencies.extend(
                            dep.split()[0]
                            for dep in dep_group
                            if isinstance(dep, str) and dep.strip()
                        )

    if dependencies:
        meta[META_DEPENDENCIES] = list(dict.fromkeys(dependencies))[:50]
    if dev_dependencies:
        meta[META_DEV_DEPENDENCIES] = list(dict.fromkeys(dev_dependencies))[:50]

    # Detect file type
    if "pyproject.toml" in p.name:
        meta[META_FILE_TYPE] = "python_project"
    elif "Cargo.toml" in p.name:
        meta[META_FILE_TYPE] = "rust_project"

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_TOML,
        metadata=meta,
    )
    return [node]


def parse_ini(path: str, *, exclude_tests: bool = False) -> list[Node]:
    """Extract metadata from INI configuration files."""
    p = Path(path)
    src = p.read_bytes()
    content = src.decode("utf-8", errors="replace")

    meta: dict[str, Any] = {}

    # Parse INI sections and keys
    sections = {}
    current_section = "default"

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue

        # Section headers
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            sections[current_section] = []
        # Key-value pairs
        elif "=" in line or ":" in line:
            separator = "=" if "=" in line else ":"
            key, _, value = line.partition(separator)
            if current_section not in sections:
                sections[current_section] = []
            sections[current_section].append(key.strip())

    if sections:
        meta[META_TOP_LEVEL_KEYS] = list(sections.keys())[:20]
        total_keys = sum(len(keys) for keys in sections.values())
        meta[META_PROPERTY_COUNT] = total_keys

    node = Node(
        id=f"{NodeKind.FILE.value}:{path}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name=p.name,
        path=path.replace("\\", "/"),
        content_hash=content_hash_bytes(src),
        language=LANG_INI,
        metadata=meta,
    )
    return [node]
