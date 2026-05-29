from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

LAYER_PATTERNS: dict[str, list[str]] = {
    "api": [
        "routes/",
        "api/",
        "endpoints/",
        "handlers/",
        "views/",
        "pages/",
        "controllers/",
    ],
    "service": [
        "services/",
        "service/",
        "usecases/",
        "use_cases/",
        "interactors/",
        "domain/",
        "logic/",
        "managers/",
    ],
    "data": [
        "models/",
        "entities/",
        "entity/",
        "schemas/",
        "repository/",
        "repositories/",
        "store/",
        "dal/",
        "persistence/",
        "db/",
    ],
    "ui": [
        "components/",
        "widgets/",
        "ui/",
        "screens/",
        "templates/",
        "layouts/",
        "partials/",
    ],
    "infra": [
        "infra/",
        "deploy/",
        "terraform/",
        "k8s/",
        "docker/",
        "helm/",
        "ansible/",
    ],
    "config": [
        "config/",
        "settings/",
        "env/",
        "migrations/",
    ],
    "test": [
        "tests/",
        "test/",
        "__tests__/",
        "spec/",
        "fixtures/",
    ],
    "middleware": [
        "middleware/",
        "interceptors/",
        "pipes/",
        "guards/",
        "filters/",
    ],
    "utils": [
        "utils/",
        "helpers/",
        "lib/",
        "common/",
        "shared/",
        "pkg/",
        "internal/",
    ],
    "entry": [
        "cmd/",
        "bin/",
        "cli/",
        "scripts/",
        "src/bin/",
    ],
}

FRAMEWORK_LAYERS: dict[str, dict[str, str]] = {
    "nextjs": {
        "app/": "api",
        "components/": "ui",
        "lib/": "service",
        "hooks/": "ui",
    },
    "django": {
        "views/": "api",
        "serializers/": "api",
        "managers/": "service",
        "signals/": "service",
    },
    "spring": {
        "controller/": "api",
        "service/": "service",
        "repository/": "data",
        "entity/": "data",
    },
    "go": {
        "cmd/": "entry",
        "internal/": "service",
        "pkg/": "utils",
    },
    "fastapi": {
        "routers/": "api",
        "schemas/": "data",
        "crud/": "data",
        "dependencies/": "middleware",
    },
    "flask": {
        "routes/": "api",
        "blueprints/": "api",
        "models/": "data",
    },
    "laravel": {
        "Http/Controllers/": "api",
        "Services/": "service",
        "Models/": "data",
        "Http/Middleware/": "middleware",
    },
}

FRAMEWORK_DETECTION_FILES: dict[str, str] = {
    "next.config.js":   "nextjs",
    "next.config.ts":   "nextjs",
    "next.config.mjs":  "nextjs",
    "manage.py":        "django",
    "pom.xml":          "spring",
    "build.gradle":     "spring",
    "build.gradle.kts": "spring",
    "go.mod":           "go",
}

EXPECTED_FLOW: dict[str, set[str]] = {
    "data":    {"utils", "config"},
    "service": {"data", "utils", "config"},
    "utils":   {"config"},
}


def detect_framework(repo_root: Path) -> str | None:
    for filename, framework in FRAMEWORK_DETECTION_FILES.items():
        if (repo_root / filename).exists():
            return framework
    for config in ("pyproject.toml", "requirements.txt", "composer.json"):
        f = repo_root / config
        if not f.exists():
            continue
        try:
            text = f.read_text(errors="replace").lower()
        except OSError:
            continue
        if "fastapi" in text:
            return "fastapi"
        if "django" in text:
            return "django"
        if "flask" in text:
            return "flask"
        if "laravel" in text:
            return "laravel"
    return None


def assign_layers_from_paths(paths: list[str], framework: str | None) -> dict[str, str]:
    """Return path → layer. Paths without match are absent from result."""
    layers: dict[str, str] = {}
    for p in paths:
        norm = p.replace("\\", "/")
        for layer_name, patterns in LAYER_PATTERNS.items():
            if any(pat in norm for pat in patterns):
                layers[p] = layer_name
                break

    if framework and framework in FRAMEWORK_LAYERS:
        for p in paths:
            norm = p.replace("\\", "/")
            for dir_pattern, layer in FRAMEWORK_LAYERS[framework].items():
                if dir_pattern in norm:
                    layers[p] = layer
                    break
    return layers


def detect_violations(layers: dict[str, str], edges) -> list[str]:
    """Diagnostic only — return list of 'X → Y (unexpected dependency)' strings."""
    deps: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        kind = str(getattr(e, "kind", ""))
        if not any(k in kind for k in ("CALLS", "IMPORTS")):
            continue
        fl = layers.get(e.from_id)
        tl = layers.get(e.to_id)
        if fl and tl and fl != tl:
            deps[fl].add(tl)
    violations: list[str] = []
    for layer, allowed in EXPECTED_FLOW.items():
        for dep in deps.get(layer, set()):
            if dep not in allowed:
                violations.append(f"{layer} → {dep} (unexpected dependency direction)")
    return violations


def assign_and_store_layers(repo, repo_root: Path) -> dict[str, int]:
    """Pass 1+2 (dir + framework override) + Pass 3 (violations at index time).

    Persists layer per node and violations in meta. Returns layer counts.
    """
    framework = detect_framework(repo_root)
    with repo.db._lock:
        conn = repo.db.connect()
        if framework:
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('framework', ?)", (framework,))
        else:
            conn.execute("DELETE FROM meta WHERE key = 'framework'")
        conn.commit()

    nodes = repo.nodes.list_all_undeleted()
    paths = list({n.path for n in nodes if n.path})
    path_to_layer = assign_layers_from_paths(paths, framework)
    counts: dict[str, int] = {}
    layer_map: dict[str, str] = {}
    for node in nodes:
        layer = path_to_layer.get(node.path)
        if layer:
            repo.nodes.update_layer(node.id, layer)
            counts[layer] = counts.get(layer, 0) + 1
            layer_map[node.id] = layer

    # Pass 3: diagnostic violations stored in meta
    edges = repo.edges.get_all()
    violations = detect_violations(layer_map, edges)
    with repo.db._lock:
        conn = repo.db.connect()
        conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('layer_violations', ?)",
            (json.dumps(violations),),
        )
        conn.commit()

    return counts
