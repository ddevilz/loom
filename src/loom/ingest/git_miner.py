from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 120

# Field separator used in git log format (Unit Separator, ASCII 0x1F).
# NUL bytes (0x00) cannot be passed through subprocess on Windows, so we use
# a character that is extremely unlikely to appear in commit messages.
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"

# Ticket reference patterns (order matters — more specific first)
_TICKET_PATTERNS: list[re.Pattern[str]] = [
    # Jira: PROJ-123, ABC-1, TEAM-9999
    re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b"),
    # GitHub closes/fixes/resolves #123
    re.compile(r"(?:closes?|fixes?|resolves?)\s+#(\d+)", re.IGNORECASE),
    # Plain GitHub #123 reference
    re.compile(r"(?<!\w)#(\d+)(?!\w)"),
    # Linear: ENG-123, TEAM-456
    re.compile(r"\b([A-Z]{2,10}-\d+)\b"),
]

_CLOSING_PATTERN: re.Pattern[str] = re.compile(
    r"(?:closes?|fixes?|resolves?)\s+", re.IGNORECASE
)


@dataclass(frozen=True)
class CommitRef:
    """A parsed commit with its ticket references and changed files."""

    sha: str
    message: str
    ticket_refs: tuple[str, ...]  # e.g. ("PROJ-42", "#99")
    changed_files: tuple[str, ...]  # relative paths
    is_closing: bool  # True if message contains "closes/fixes/resolves"


@dataclass
class MiningResult:
    """Result of mining a repo's git log for ticket references."""

    commit_refs: list[CommitRef] = field(default_factory=list)
    # Maps ticket_ref -> set of file paths modified by commits referencing that ticket
    ticket_to_files: dict[str, set[str]] = field(default_factory=dict)
    # Maps file_path -> set of ticket refs from commits that modified it
    file_to_tickets: dict[str, set[str]] = field(default_factory=dict)


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


def _extract_ticket_refs(message: str) -> tuple[tuple[str, ...], bool]:
    """Extract ticket references from a commit message.

    Args:
        message: The commit message (subject + body)

    Returns:
        Tuple of (unique refs found, is_closing).
        is_closing is True if the message uses closing keywords before a ref.
    """
    is_closing = bool(_CLOSING_PATTERN.search(message))

    seen: dict[str, None] = {}  # ordered set via dict
    for pattern in _TICKET_PATTERNS:
        for match in pattern.finditer(message):
            ref = match.group(1)
            # Normalise plain GitHub numbers to "#NNN" form
            if ref.isdigit():
                ref = f"#{ref}"
            seen[ref] = None

    return tuple(seen.keys()), is_closing


def _parse_commit_log(log_output: str) -> list[dict[str, str]]:
    """Parse output from ``git log --format="..."`` using _RECORD_SEP / _FIELD_SEP.

    Format string used: ``%H<FS>%s<FS>%b<RS>`` where FS=0x1F, RS=0x1E.

    Args:
        log_output: Raw stdout from the git log command.

    Returns:
        List of dicts with keys ``sha`` and ``message`` (subject + body).
    """
    commits: list[dict[str, str]] = []
    if not log_output.strip():
        return commits

    for record in log_output.split(_RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        fields = record.split(_FIELD_SEP)
        if len(fields) < 2:
            continue
        sha = fields[0].strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        subject = fields[1].strip() if len(fields) > 1 else ""
        body = fields[2].strip() if len(fields) > 2 else ""
        message = (subject + " " + body).strip()
        commits.append({"sha": sha, "message": message})

    return commits


def _get_changed_files_for_commit(repo_path: str, sha: str) -> list[str]:
    """Return list of Added or Modified files for a single commit.

    Args:
        repo_path: Path to git repository.
        sha: Commit SHA to inspect.

    Returns:
        Relative file paths that were added or modified (not deleted).
    """
    try:
        out = _run_git(
            repo_path,
            [
                "diff-tree",
                "--no-commit-id",
                "-r",
                "--name-only",
                "--diff-filter=AM",
                sha,
            ],
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("git_miner: diff-tree failed for %s: %s", sha, exc)
        return []

    return [line for line in out.splitlines() if line.strip()]


async def mine_repo(
    repo_path: str,
    *,
    max_commits: int = 5000,
    since: str | None = None,
) -> MiningResult:
    """Mine a git repository's commit history for ticket references.

    For each commit that references a ticket ID, records which files were
    modified so that ``REALIZES`` / ``CLOSES`` edges can be created between
    code nodes and ticket nodes.

    Args:
        repo_path: Absolute path to the git repository root.
        max_commits: Safety cap — never read more than this many commits.
        since: Optional ISO date / git date string passed to ``--since``.

    Returns:
        A :class:`MiningResult` populated with commit refs and index maps.
    """
    result = MiningResult()

    # Build git log command.
    # Use ASCII Unit Separator (0x1F) between fields and Record Separator (0x1E)
    # between commits.  NUL bytes cannot be used on Windows subprocess args.
    fmt = f"%H{_FIELD_SEP}%s{_FIELD_SEP}%b{_RECORD_SEP}"
    log_args: list[str] = [
        "log",
        f"--format={fmt}",
        "--no-merges",
        f"--max-count={max_commits}",
    ]
    if since:
        log_args.append(f"--since={since}")

    try:
        log_output = await asyncio.to_thread(_run_git, repo_path, log_args)
    except subprocess.CalledProcessError as exc:
        logger.warning("git_miner: git log failed: %s", exc)
        return result
    except subprocess.TimeoutExpired:
        logger.warning("git_miner: git log timed out")
        return result

    parsed = _parse_commit_log(log_output)
    if not parsed:
        logger.info("git_miner: no commits found in %s", repo_path)
        return result

    # Filter to only commits that reference at least one ticket
    commits_with_refs: list[tuple[dict[str, str], tuple[str, ...], bool]] = []
    for commit in parsed:
        refs, is_closing = _extract_ticket_refs(commit["message"])
        if refs:
            commits_with_refs.append((commit, refs, is_closing))

    if not commits_with_refs:
        logger.info(
            "git_miner: %d commits scanned, 0 with ticket refs", len(parsed)
        )
        return result

    # Fetch changed files in batches of 20
    BATCH_SIZE = 20

    async def _fetch_files(sha: str) -> list[str]:
        return await asyncio.to_thread(_get_changed_files_for_commit, repo_path, sha)

    all_changed: list[list[str]] = []
    for batch_start in range(0, len(commits_with_refs), BATCH_SIZE):
        batch = commits_with_refs[batch_start : batch_start + BATCH_SIZE]
        batch_results = await asyncio.gather(
            *[_fetch_files(c[0]["sha"]) for c in batch]
        )
        all_changed.extend(batch_results)

    # Assemble CommitRef objects and populate index maps
    for (commit, refs, is_closing), changed_files in zip(
        commits_with_refs, all_changed
    ):
        commit_ref = CommitRef(
            sha=commit["sha"],
            message=commit["message"],
            ticket_refs=refs,
            changed_files=tuple(changed_files),
            is_closing=is_closing,
        )
        result.commit_refs.append(commit_ref)

        for ref in refs:
            result.ticket_to_files.setdefault(ref, set()).update(changed_files)
            for fpath in changed_files:
                result.file_to_tickets.setdefault(fpath, set()).add(ref)

    logger.info(
        "git_miner: %d commits, %d ticket refs, %d files",
        len(result.commit_refs),
        len(result.ticket_to_files),
        len(result.file_to_tickets),
    )
    return result


def tickets_for_file(path: str, mining_result: MiningResult) -> set[str]:
    """Return the set of ticket refs that modified *path*, or empty set.

    Args:
        path: Relative file path (as stored in the git index).
        mining_result: Output from :func:`mine_repo`.

    Returns:
        Set of ticket ref strings (e.g. ``{"PROJ-42", "#99"}``).
    """
    return set(mining_result.file_to_tickets.get(path, set()))


def files_for_ticket(ticket_ref: str, mining_result: MiningResult) -> set[str]:
    """Return the set of file paths modified by commits referencing *ticket_ref*.

    Args:
        ticket_ref: A ticket reference string (e.g. ``"PROJ-42"`` or ``"#99"``).
        mining_result: Output from :func:`mine_repo`.

    Returns:
        Set of relative file paths.
    """
    return set(mining_result.ticket_to_files.get(ticket_ref, set()))
