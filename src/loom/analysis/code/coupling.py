from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import git

from loom.core import Edge, EdgeType

logger = logging.getLogger(__name__)


def analyze_coupling(
    repo_path: str,
    months: int = 6,
    threshold: float = 0.3,
) -> list[Edge]:
    """Analyze git history to find files that frequently change together.
    
    Args:
        repo_path: Path to git repository
        months: Number of months of history to analyze (default: 6)
        threshold: Minimum coupling frequency to create edge (default: 0.3)
    
    Returns:
        List of COUPLED_WITH edges for file pairs exceeding threshold
    
    Notes:
        - Edge confidence = coupling frequency (0.3-1.0)
        - Merge commits are handled (not double-counted)
        - Returns empty list for repos with no history
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logger.warning(f"Not a valid git repository: {repo_path} - {e}")
        return []
    
    # Calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=months * 30)
    
    # Collect changed files per commit
    file_changes_per_commit: list[set[str]] = []
    file_appearance_count: dict[str, int] = defaultdict(int)
    
    try:
        commits = list(repo.iter_commits(since=cutoff_date.isoformat()))
    except git.GitCommandError as e:
        logger.warning(f"Failed to read commits: {e}")
        return []
    
    if not commits:
        logger.info(f"No commits found in last {months} months")
        return []
    
    logger.info(f"Analyzing {len(commits)} commits from last {months} months")
    
    for commit in commits:
        # Get changed files for this commit
        changed_files: set[str] = set()
        
        if commit.parents:
            # Normal commit: diff against first parent
            try:
                diffs = commit.diff(commit.parents[0])
                for diff_item in diffs:
                    # Use a_path (source path) for changed files
                    if diff_item.a_path:
                        changed_files.add(diff_item.a_path)
                    # Also check b_path for new files
                    if diff_item.b_path and diff_item.a_path != diff_item.b_path:
                        changed_files.add(diff_item.b_path)
            except Exception as e:
                logger.debug(f"Failed to diff commit {commit.hexsha[:8]}: {e}")
                continue
        else:
            # Initial commit: all files are new
            try:
                for item in commit.tree.traverse():
                    if item.type == "blob":
                        changed_files.add(item.path)
            except Exception as e:
                logger.debug(f"Failed to traverse initial commit {commit.hexsha[:8]}: {e}")
                continue
        
        if changed_files:
            file_changes_per_commit.append(changed_files)
            for file_path in changed_files:
                file_appearance_count[file_path] += 1
    
    if not file_changes_per_commit:
        logger.info("No file changes found in commit history")
        return []
    
    # Calculate coupling frequencies
    pair_cooccurrence: dict[tuple[str, str], int] = defaultdict(int)
    
    for changed_files in file_changes_per_commit:
        # Get all pairs of files that changed together
        for file_a, file_b in combinations(sorted(changed_files), 2):
            pair_cooccurrence[(file_a, file_b)] += 1
    
    # Create edges for pairs exceeding threshold
    edges: list[Edge] = []
    
    for (file_a, file_b), cooccurrence_count in pair_cooccurrence.items():
        # Calculate coupling frequency: how often they appear together
        # relative to how often either appears
        appearances_a = file_appearance_count[file_a]
        appearances_b = file_appearance_count[file_b]
        
        # Coupling frequency = cooccurrence / max(appearances)
        # This measures: "when file A changes, how often does B also change?"
        max_appearances = max(appearances_a, appearances_b)
        coupling_frequency = cooccurrence_count / max_appearances
        
        if coupling_frequency >= threshold:
            # Map coupling frequency to confidence (0.3-1.0 → 0.3-1.0)
            confidence = coupling_frequency
            
            # Create bidirectional edges (A coupled with B, B coupled with A)
            edges.append(
                Edge(
                    from_id=f"file:{file_a}",
                    to_id=f"file:{file_b}",
                    kind=EdgeType.COUPLED_WITH,
                    confidence=confidence,
                    metadata={
                        "coupling_frequency": coupling_frequency,
                        "cooccurrence_count": cooccurrence_count,
                        "file_a_appearances": appearances_a,
                        "file_b_appearances": appearances_b,
                        "analysis_months": months,
                    },
                )
            )
            
            edges.append(
                Edge(
                    from_id=f"file:{file_b}",
                    to_id=f"file:{file_a}",
                    kind=EdgeType.COUPLED_WITH,
                    confidence=confidence,
                    metadata={
                        "coupling_frequency": coupling_frequency,
                        "cooccurrence_count": cooccurrence_count,
                        "file_a_appearances": appearances_b,
                        "file_b_appearances": appearances_a,
                        "analysis_months": months,
                    },
                )
            )
    
    logger.info(
        f"Found {len(edges) // 2} coupled file pairs "
        f"(threshold={threshold}, {len(file_changes_per_commit)} commits analyzed)"
    )
    
    return edges
