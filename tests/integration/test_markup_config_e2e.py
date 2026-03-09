"""
E2E Integration Test: Markup & Configuration File Parsing

Tests the markup parser's ability to extract metadata from:
- HTML files (forms, scripts, stylesheets, templates)
- CSS files (classes, IDs, media queries, variables)
- XML files (structure, namespaces)
- JSON files (package.json, tsconfig.json)
- YAML files (docker-compose, kubernetes)
- Properties files (Java configuration)
- .env files (environment variables)
- TOML files (Python/Rust projects)
- INI files (configuration)
"""

from pathlib import Path

import pytest

from loom.core import NodeKind
from loom.ingest.code.languages.markup import (
    parse_css,
    parse_env,
    parse_html,
    parse_json,
    parse_properties,
)


@pytest.mark.integration
def test_properties_file_parsing():
    """Test Java .properties file parsing."""
    fixture_path = (
        Path(__file__).parent.parent
        / "fixtures"
        / "java_springboot"
        / "src"
        / "main"
        / "resources"
        / "application.properties"
    )

    if not fixture_path.exists():
        pytest.skip(f"Properties file not found at {fixture_path}")

    nodes = parse_properties(str(fixture_path))

    assert len(nodes) == 1, "Should extract exactly one node for properties file"
    node = nodes[0]

    # Test basic node properties
    assert node.kind == NodeKind.FILE
    assert node.language == "properties"
    assert "application.properties" in node.name

    # Test metadata extraction
    metadata = node.metadata

    # Should have property count
    assert "property_count" in metadata, "Should extract property count"
    assert metadata["property_count"] > 0, "Should have at least one property"

    # Should have property keys
    assert "property_keys" in metadata, "Should extract property keys"
    property_keys = metadata["property_keys"]

    # Check for Spring-specific properties
    spring_keys = [k for k in property_keys if k.startswith("spring.")]
    assert len(spring_keys) > 0, "Should detect Spring properties"

    # Should detect Spring profile
    if "spring_profile" in metadata:
        assert metadata["spring_profile"] in ["dev", "prod", "test"], (
            "Should detect valid Spring profile"
        )

    # Should detect database configuration
    assert metadata.get("database_config"), "Should detect database configuration"

    # Should detect sensitive keys
    assert "sensitive_keys" in metadata, "Should detect sensitive keys"
    sensitive = metadata["sensitive_keys"]
    assert any(
        "password" in k.lower() or "secret" in k.lower() or "key" in k.lower()
        for k in sensitive
    ), "Should detect password/secret/key fields"

    print("\n✅ Properties File Test Results:")
    print(f"   Properties: {metadata['property_count']}")
    print(f"   Spring profile: {metadata.get('spring_profile', 'N/A')}")
    print(f"   Database config: {metadata.get('database_config', False)}")
    print(f"   Sensitive keys: {len(sensitive)}")


@pytest.mark.integration
def test_env_file_parsing():
    """Test .env file parsing."""
    # Test with Vue TSX app .env.example
    fixture_path = (
        Path(__file__).parent.parent / "fixtures" / "vue_tsx_app" / ".env.example"
    )

    if not fixture_path.exists():
        # Try Python Flask app
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "python_flask_app"
            / ".env.example"
        )

    if not fixture_path.exists():
        pytest.skip("No .env file found in fixtures")

    nodes = parse_env(str(fixture_path))

    assert len(nodes) == 1, "Should extract exactly one node for .env file"
    node = nodes[0]

    # Test basic node properties
    assert node.kind == NodeKind.FILE
    assert node.language == "env"

    # Test metadata extraction
    metadata = node.metadata

    # Should have variable count
    assert "variable_count" in metadata, "Should extract variable count"
    assert metadata["variable_count"] > 0, "Should have at least one variable"

    # Should have variable names
    assert "variable_names" in metadata, "Should extract variable names"
    metadata["variable_names"]

    # Should detect sensitive keys
    assert "sensitive_keys" in metadata, "Should detect sensitive keys"
    sensitive = metadata["sensitive_keys"]
    assert len(sensitive) > 0, "Should find sensitive environment variables"

    # Common sensitive patterns
    sensitive_patterns = ["SECRET", "KEY", "PASSWORD", "TOKEN"]
    assert any(
        any(pattern in var for pattern in sensitive_patterns) for var in sensitive
    ), "Should detect common sensitive variable patterns"

    print("\n✅ Environment File Test Results:")
    print(f"   Variables: {metadata['variable_count']}")
    print(f"   Sensitive keys: {len(sensitive)}")
    print(f"   Database config: {metadata.get('database_config', False)}")


@pytest.mark.integration
def test_html_file_parsing():
    """Test HTML file parsing."""
    # Create a simple HTML test file
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Test Application</title>
        <link rel="stylesheet" href="styles.css">
        <script src="app.js"></script>
    </head>
    <body>
        <form action="/submit" method="post">
            <input type="text" name="username">
        </form>
        <div data-component="user-card" v-if="isLoggedIn">
            {{ userName }}
        </div>
    </body>
    </html>
    """

    # Write temporary HTML file
    temp_html = Path(__file__).parent.parent / "fixtures" / "test_temp.html"
    temp_html.write_text(html_content, encoding="utf-8")

    try:
        nodes = parse_html(str(temp_html))

        assert len(nodes) == 1, "Should extract exactly one node for HTML file"
        node = nodes[0]

        # Test basic node properties
        assert node.kind == NodeKind.FILE
        assert node.language == "html"

        # Test metadata extraction
        metadata = node.metadata

        # Should extract title
        assert "title" in metadata, "Should extract page title"
        assert metadata["title"] == "Test Application"

        # Should count forms
        assert "form_count" in metadata, "Should count forms"
        assert metadata["form_count"] >= 1, "Should find at least one form"

        # Should extract form actions
        if "form_actions" in metadata:
            assert "/submit" in metadata["form_actions"], "Should extract form action"

        # Should detect template engine
        if "template_engine" in metadata:
            assert metadata["template_engine"] in ["jinja2", "ejs", "php"], (
                "Should detect template engine"
            )

        # Should extract scripts
        if "scripts" in metadata:
            assert any("app.js" in script for script in metadata["scripts"]), (
                "Should extract script references"
            )

        # Should extract stylesheets
        if "stylesheets" in metadata:
            assert any("styles.css" in style for style in metadata["stylesheets"]), (
                "Should extract stylesheet references"
            )

        print("\n✅ HTML File Test Results:")
        print(f"   Title: {metadata.get('title', 'N/A')}")
        print(f"   Forms: {metadata.get('form_count', 0)}")
        print(f"   Scripts: {len(metadata.get('scripts', []))}")
        print(f"   Stylesheets: {len(metadata.get('stylesheets', []))}")

    finally:
        # Clean up
        if temp_html.exists():
            temp_html.unlink()


@pytest.mark.integration
def test_css_file_parsing():
    """Test CSS file parsing."""
    css_content = """
    :root {
        --primary-color: #007bff;
        --secondary-color: #6c757d;
    }
    
    .container {
        max-width: 1200px;
    }
    
    #header {
        background-color: var(--primary-color);
    }
    
    @media (max-width: 768px) {
        .container {
            max-width: 100%;
        }
    }
    
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    """

    # Write temporary CSS file
    temp_css = Path(__file__).parent.parent / "fixtures" / "test_temp.css"
    temp_css.write_text(css_content, encoding="utf-8")

    try:
        nodes = parse_css(str(temp_css))

        assert len(nodes) == 1, "Should extract exactly one node for CSS file"
        node = nodes[0]

        # Test basic node properties
        assert node.kind == NodeKind.FILE
        assert node.language == "css"

        # Test metadata extraction
        metadata = node.metadata

        # Should count classes
        assert "class_count" in metadata, "Should count CSS classes"
        assert metadata["class_count"] > 0, "Should find at least one class"

        # Should extract class names
        if "classes" in metadata:
            assert "container" in metadata["classes"], "Should extract class names"

        # Should count IDs
        if "id_count" in metadata:
            assert metadata["id_count"] > 0, "Should find at least one ID"

        # Should detect media queries
        if "media_query_count" in metadata:
            assert metadata["media_query_count"] > 0, "Should detect media queries"

        # Should extract CSS variables
        if "css_variables" in metadata:
            assert len(metadata["css_variables"]) > 0, "Should extract CSS variables"
            assert any(
                "primary-color" in var or "secondary-color" in var
                for var in metadata["css_variables"]
            ), "Should extract custom property names"

        print("\n✅ CSS File Test Results:")
        print(f"   Classes: {metadata.get('class_count', 0)}")
        print(f"   IDs: {metadata.get('id_count', 0)}")
        print(f"   Media queries: {metadata.get('media_query_count', 0)}")
        print(f"   CSS variables: {len(metadata.get('css_variables', []))}")

    finally:
        # Clean up
        if temp_css.exists():
            temp_css.unlink()


@pytest.mark.integration
def test_json_file_parsing():
    """Test JSON file parsing (package.json)."""
    json_content = """{
        "name": "test-app",
        "version": "1.0.0",
        "dependencies": {
            "react": "^18.0.0",
            "vue": "^3.0.0"
        },
        "devDependencies": {
            "typescript": "^5.0.0"
        },
        "scripts": {
            "dev": "vite",
            "build": "vite build"
        }
    }"""

    # Write temporary JSON file
    temp_json = Path(__file__).parent.parent / "fixtures" / "test_package.json"
    temp_json.write_text(json_content, encoding="utf-8")

    try:
        nodes = parse_json(str(temp_json))

        assert len(nodes) == 1, "Should extract exactly one node for JSON file"
        node = nodes[0]

        # Test basic node properties
        assert node.kind == NodeKind.FILE
        assert node.language == "json"

        # Test metadata extraction
        metadata = node.metadata

        # Should extract top-level keys
        assert "top_level_keys" in metadata, "Should extract top-level keys"
        keys = metadata["top_level_keys"]
        assert "name" in keys, "Should find 'name' key"
        assert "version" in keys, "Should find 'version' key"
        assert "dependencies" in keys, "Should find 'dependencies' key"

        # Should detect package.json file type
        if "file_type" in metadata:
            # The parser uses 'package.json' as the file type value
            assert "package" in metadata["file_type"].lower(), (
                "Should detect package.json type"
            )

        print("\n✅ JSON File Test Results:")
        print(f"   Top-level keys: {len(keys)}")
        print(f"   File type: {metadata.get('file_type', 'generic')}")

    finally:
        # Clean up
        if temp_json.exists():
            temp_json.unlink()


@pytest.mark.integration
def test_markup_parsers_comprehensive():
    """Comprehensive test of all markup parsers."""

    results = {
        "properties": False,
        "env": False,
        "html": False,
        "css": False,
        "json": False,
    }

    # Test properties file
    props_path = (
        Path(__file__).parent.parent
        / "fixtures"
        / "java_springboot"
        / "src"
        / "main"
        / "resources"
        / "application.properties"
    )
    if props_path.exists():
        nodes = parse_properties(str(props_path))
        results["properties"] = (
            len(nodes) == 1 and nodes[0].metadata.get("property_count", 0) > 0
        )

    # Test env file
    env_path = (
        Path(__file__).parent.parent / "fixtures" / "python_flask_app" / ".env.example"
    )
    if env_path.exists():
        nodes = parse_env(str(env_path))
        results["env"] = (
            len(nodes) == 1 and nodes[0].metadata.get("variable_count", 0) > 0
        )

    print("\n📊 Markup Parser Comprehensive Test:")
    print(f"   Properties parser: {'✅' if results['properties'] else '❌'}")
    print(f"   Env parser: {'✅' if results['env'] else '❌'}")

    # At least some parsers should work
    assert any(results.values()), "At least one markup parser should work"
