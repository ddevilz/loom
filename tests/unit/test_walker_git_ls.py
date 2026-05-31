import subprocess
from pathlib import Path

from loom.indexer.walker import _git_ls_files, walk_repo


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def test_git_ls_files_discovers_multi_module_java(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    # Multi-module Maven layout
    (tmp_path / "module-a" / "src" / "main" / "java" / "com" / "x").mkdir(parents=True)
    (tmp_path / "module-b" / "src" / "main" / "java" / "com" / "y").mkdir(parents=True)
    (tmp_path / "module-a" / "src" / "main" / "java" / "com" / "x" / "A.java").write_text(
        "class A {}"
    )
    (tmp_path / "module-b" / "src" / "main" / "java" / "com" / "y" / "B.java").write_text(
        "class B {}"
    )
    (tmp_path / "module-a" / "pom.xml").write_text("<project/>")
    (tmp_path / "pom.xml").write_text("<project/>")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    files = _git_ls_files(tmp_path)
    assert files is not None
    assert any("A.java" in f for f in files)
    assert any("B.java" in f for f in files)


def test_git_ls_files_returns_none_for_non_git(tmp_path: Path) -> None:
    # No git init
    (tmp_path / "foo.py").write_text("x = 1")
    assert _git_ls_files(tmp_path) is None


def test_walk_repo_finds_java_in_multi_module(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "module-a" / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "module-a" / "src" / "main" / "java" / "A.java").write_text("class A {}")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    result = walk_repo(str(tmp_path))
    assert "java" in result
    assert len(result["java"]) == 1
    assert result["java"][0].endswith("A.java")


def test_walk_repo_fallback_for_non_git(tmp_path: Path) -> None:
    # Non-git repo — falls back to directory walker
    (tmp_path / "a.py").write_text("x = 1")
    result = walk_repo(str(tmp_path))
    assert "python" in result
    assert len(result["python"]) == 1
