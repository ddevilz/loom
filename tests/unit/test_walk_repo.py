from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from loom.ingest.code.walker import walk_repo


def _touch(p: Path, content: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_walk_repo_groups_by_language(tmp_path: Path):
    _touch(tmp_path / "a.py", "def a():\n  pass\n")
    _touch(tmp_path / "b.ts", "function b() {}\n")
    _touch(tmp_path / "c.go", "package main\nfunc c() {}\n")
    _touch(tmp_path / "d.html", "<html></html>")
    _touch(tmp_path / "e.css", ".x { color: red; }")
    _touch(tmp_path / "ignored.bin", "")

    out = walk_repo(str(tmp_path))

    assert "python" in out
    assert "typescript" in out
    assert "go" in out
    assert "html" in out
    assert "css" in out

    assert any(p.endswith("a.py") for p in out["python"])
    assert any(p.endswith("b.ts") for p in out["typescript"])
    assert any(p.endswith("c.go") for p in out["go"])


def test_walk_repo_respects_gitignore(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(
        "ignored.py\nsecret/**\n",
        encoding="utf-8",
    )

    _touch(tmp_path / "ok.py", "def ok():\n  pass\n")
    _touch(tmp_path / "ignored.py", "def bad():\n  pass\n")
    _touch(tmp_path / "secret" / "a.py", "def secret():\n  pass\n")

    out = walk_repo(str(tmp_path))

    assert any(p.endswith("ok.py") for p in out.get("python", []))
    assert not any(p.endswith("ignored.py") for p in out.get("python", []))
    assert not any("secret" in p.replace("\\", "/") for p in out.get("python", []))


def test_walk_repo_skips_default_dirs(tmp_path: Path):
    _touch(tmp_path / "app.py", "def app():\n  pass\n")

    for d in ["node_modules", "vendor", "dist", "build", ".venv", "__pycache__", ".git"]:
        _touch(tmp_path / d / "x.py", "def x():\n  pass\n")

    out = walk_repo(str(tmp_path))

    assert any(p.endswith("app.py") for p in out.get("python", []))
    for d in ["node_modules", "vendor", "dist", "build", ".venv", "__pycache__", ".git"]:
        assert not any(d in p.replace("\\", "/") for p in out.get("python", []))


def test_walk_repo_skips_hidden_dirs(tmp_path: Path):
    _touch(tmp_path / "app.py", "def app():\n  pass\n")
    _touch(tmp_path / ".hidden" / "x.py", "def x():\n  pass\n")

    out = walk_repo(str(tmp_path))

    assert any(p.endswith("app.py") for p in out.get("python", []))
    assert not any("/.hidden/" in p.replace("\\", "/") for p in out.get("python", []))


def test_walk_repo_handles_symlink_dir_without_loop(tmp_path: Path):
    # Symlinks are not always allowed on Windows without admin/dev mode.
    # If creation fails, skip.
    target = tmp_path / "real"
    target.mkdir()
    _touch(target / "a.py", "def a():\n  pass\n")

    link = tmp_path / "link"
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported")

    out = walk_repo(str(tmp_path))
    assert any(p.endswith("a.py") for p in out.get("python", []))
    # should not traverse link/, so only one copy
    assert len([p for p in out.get("python", []) if p.endswith("a.py")]) == 1


def test_walk_repo_performance_sanity(tmp_path: Path):
    # Create 150 files, should still be fast
    for i in range(150):
        _touch(tmp_path / f"mod_{i}.py", f"def f{i}():\n  pass\n")

    start = time.perf_counter()
    out = walk_repo(str(tmp_path))
    elapsed = time.perf_counter() - start

    assert len(out.get("python", [])) == 150
    assert elapsed < 2.0


def test_walk_repo_returns_absolute_posix_paths(tmp_path: Path):
    target = tmp_path / "nested" / "app.py"
    _touch(target, "def app():\n  pass\n")

    out = walk_repo(str(tmp_path))

    python_files = out.get("python", [])
    assert python_files == [target.resolve().as_posix()]
