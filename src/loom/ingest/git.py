from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import Literal

from loom.ingest.code.registry import get_registry

logger = logging.getLogger(__name__)

# Timeout for git operations (in seconds)
_GIT_TIMEOUT = 60


@dataclass(frozen=True)
class FileChange:
    status: Literal["A", "M", "D", "R"]
    path: str
    old_path: str | None = None


def _run_git(repo_path: str, args: list[str]) -> str:
    """Run git command with timeout and error handling.

    Args:
        repo_path: Path to git repository
        args: Git command arguments

    Returns:
        Command stdout output

    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout
        subprocess.CalledProcessError: If git command fails
    """
    p = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        timeout=_GIT_TIMEOUT,
    )
    return p.stdout


def _is_supported(path: str) -> bool:
    reg = get_registry()
    return not reg.should_skip_path(path)


def _parse_name_status_output(out: str) -> list[FileChange]:
    changes: list[FileChange] = []
    for raw_line in out.splitlines():
        line = raw_line.strip("\n")
        if not line:
            continue

        parts = line.split("\t")
        status_part = parts[0]
        status = status_part[0]

        if status == "R":
            # git diff --name-status uses: R<score>\told\tnew
            if len(parts) >= 3:
                old_path = parts[1]
                new_path = parts[2]
                if _is_supported(new_path):
                    changes.append(
                        FileChange(status="R", path=new_path, old_path=old_path)
                    )
            continue

        if status in {"A", "M", "D"}:
            if len(parts) >= 2:
                path = parts[1]
                if _is_supported(path):
                    changes.append(FileChange(status=status, path=path))
            continue

    return changes


async def get_changed_files(
    repo_path: str, old_sha: str, new_sha: str
) -> list[FileChange]:
    cmd = ["diff", "--name-status", "--find-renames=10%", f"{old_sha}..{new_sha}"]
    out = await asyncio.to_thread(_run_git, repo_path, cmd)
    return _parse_name_status_output(out)


async def get_current_sha(repo_path: str) -> str:
    out = await asyncio.to_thread(_run_git, repo_path, ["rev-parse", "HEAD"])
    return out.strip()


async def get_previous_sha(repo_path: str, ref: str = "HEAD~1") -> str:
    out = await asyncio.to_thread(_run_git, repo_path, ["rev-parse", ref])
    return out.strip()
