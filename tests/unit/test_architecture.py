from pathlib import Path

from loom.intelligence.architecture import (
    FRAMEWORK_LAYERS,
    LAYER_PATTERNS,
    assign_layers_from_paths,
    detect_framework,
    detect_violations,
)


def test_layer_patterns_includes_known_dirs():
    assert "api/" in LAYER_PATTERNS["api"]
    assert "services/" in LAYER_PATTERNS["service"]
    assert "models/" in LAYER_PATTERNS["data"]


def test_detect_framework_django(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("import django\n")
    assert detect_framework(tmp_path) == "django"


def test_detect_framework_spring(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>")
    assert detect_framework(tmp_path) == "spring"


def test_detect_framework_none(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hi")
    assert detect_framework(tmp_path) is None


def test_assign_layers_directory_patterns():
    paths = [
        "src/api/routes/users.py",
        "src/services/order_service.py",
        "src/models/user.py",
        "src/utils/helpers.py",
        "src/random/other.py",
    ]
    layers = assign_layers_from_paths(paths, framework=None)
    assert layers["src/api/routes/users.py"] == "api"
    assert layers["src/services/order_service.py"] == "service"
    assert layers["src/models/user.py"] == "data"
    assert layers["src/utils/helpers.py"] == "utils"
    assert "src/random/other.py" not in layers


def test_assign_layers_framework_override_spring():
    paths = ["app/controller/UserController.java", "app/repository/UserRepo.java"]
    layers = assign_layers_from_paths(paths, framework="spring")
    assert layers["app/controller/UserController.java"] == "api"
    assert layers["app/repository/UserRepo.java"] == "data"


def test_detect_violations_data_to_api():
    layers = {"a": "data", "b": "api"}

    class E:
        def __init__(self, f, t, k):
            self.from_id, self.to_id, self.kind = f, t, k

    edges = [E("a", "b", "CALLS")]
    violations = detect_violations(layers, edges)
    assert any("data" in v and "api" in v for v in violations)
