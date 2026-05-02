from __future__ import annotations

import importlib
import importlib.metadata
import sys
from pathlib import Path


def _parse_dependencies_from_pyproject(pyproject_text: str) -> list[str]:
    in_project = False
    in_deps = False
    deps: list[str] = []

    for raw in pyproject_text.splitlines():
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            in_project = section == "project"
            in_deps = False
            continue

        if not in_project:
            continue

        if line.startswith("dependencies") and "[" in line:
            in_deps = True
            after = line.split("[", 1)[1]
            if "]" in after:
                inner = after.split("]", 1)[0]
                deps.extend(_parse_inline_list(inner))
                in_deps = False
            continue

        if in_deps:
            if line.startswith("]"):
                in_deps = False
                continue
            deps.extend(_parse_inline_list(line.rstrip(",")))

    return deps


def _parse_inline_list(s: str) -> list[str]:
    items: list[str] = []
    cur = ""
    in_quote: str | None = None

    for ch in s:
        if in_quote:
            if ch == in_quote:
                in_quote = None
                items.append(cur)
                cur = ""
            else:
                cur += ch
        else:
            if ch in ("'", '"'):
                in_quote = ch
            else:
                continue

    return [i.strip() for i in items if i.strip()]


def _import_name_from_requirement(req: str) -> str:
    # Very small heuristic: take the distribution name before any version markers.
    # Then convert '-' to '_' for import attempts.
    head = req
    for sep in (";", " ", "<", ">", "=", "!", "~"):
        head = head.split(sep, 1)[0]
    head = head.strip()
    return head.replace("-", "_")


def _dist_name_from_requirement(req: str) -> str:
    head = req.split(";", 1)[0].strip()
    for sep in (" ", "<", ">", "=", "!", "~"):
        head = head.split(sep, 1)[0]
    return head.strip()


def _marker_allows_requirement(req: str) -> bool:
    if ";" not in req:
        return True

    marker = req.split(";", 1)[1].strip()

    # Minimal support for the only markers we currently have in pyproject.toml.
    # If we don't understand the marker, we keep the requirement (better to be noisy than silent).
    if marker == "platform_system != 'Windows'":
        return sys.platform != "win32"
    if marker == "platform_system == 'Windows'":
        return sys.platform == "win32"

    return True


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    pyproject = root / "pyproject.toml"

    if not pyproject.exists():
        print("pyproject.toml not found")
        return 2

    deps = _parse_dependencies_from_pyproject(pyproject.read_text(encoding="utf-8"))

    if not deps:
        print("No dependencies declared in pyproject.toml ([project].dependencies is empty).")
        return 0

    failed: list[str] = []
    for req in deps:
        if not _marker_allows_requirement(req):
            continue

        dist = _dist_name_from_requirement(req)
        try:
            importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            failed.append(f"{req} (distribution {dist!r} not installed)")
        except Exception as e:
            failed.append(f"{req} (failed to inspect distribution {dist!r}: {e})")

    if failed:
        print("Missing/unimportable dependencies:")
        for f in failed:
            print(f"- {f}")
        return 1

    print("All declared dependencies appear importable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
