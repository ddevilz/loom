from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from loom.ingest.git import FileChange, get_changed_files


def _git(cwd: str, *args: str) -> str:
    p = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return p.stdout


@pytest.mark.asyncio
async def test_get_changed_files_filters_and_handles_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "test@example.com")
    _git(str(repo), "config", "user.name", "Test")

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "img.jpg").write_bytes(b"\x00\x01")

    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "init")

    # Add b.ts in a second commit.
    (repo / "b.ts").write_text("function x() { return 1 }\n", encoding="utf-8")
    _git(str(repo), "add", "b.ts")
    _git(str(repo), "commit", "-m", "add b.ts")
    old = _git(str(repo), "rev-parse", "HEAD").strip()

    # Rename a.py -> a_renamed.py, modify it, and delete b.ts.

    _git(str(repo), "mv", "a.py", "a_renamed.py")
    (repo / "a_renamed.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(str(repo), "rm", "b.ts")

    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "rename and modify")
    new = _git(str(repo), "rev-parse", "HEAD").strip()

    changes = await get_changed_files(str(repo), old, new)

    # Ensure unsupported jpg is filtered out
    assert all(not c.path.endswith(".jpg") for c in changes)

    # Ensure rename is present
    renames = [c for c in changes if c.status == "R"]
    assert renames
    assert renames[0].old_path is not None
    assert renames[0].path.endswith("a_renamed.py")

    # Ensure delete is present for b.ts (supported extension)
    assert any(c.status == "D" and c.path.endswith("b.ts") for c in changes)
