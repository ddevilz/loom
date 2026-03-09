from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import Mock, patch

import git
import pytest

from loom.analysis.code.coupling import analyze_coupling
from loom.core import EdgeType


def _file_node_id(repo_root: str, rel_path: str) -> str:
    return f"file:{str((Path(repo_root) / rel_path).resolve())}"


async def test_analyze_coupling_invalid_repo(tmp_path: Path):
    """Test that invalid repos return empty list."""
    non_repo = tmp_path / "not_a_repo"
    non_repo.mkdir()

    edges = await analyze_coupling(str(non_repo))
    assert edges == []


async def test_analyze_coupling_resolves_parent_git_repo_for_subfolder():
    """Test that coupling analysis can resolve the nearest parent git repo."""
    mock_repo = Mock(spec=git.Repo)
    mock_repo.iter_commits.return_value = []
    mock_repo.working_tree_dir = "/fake/repo"

    with patch("git.Repo", return_value=mock_repo) as repo_ctor:
        edges = await analyze_coupling("/fake/repo/subdir")

    assert edges == []
    repo_ctor.assert_called_once_with(
        "/fake/repo/subdir", search_parent_directories=True
    )


async def test_analyze_coupling_no_commits():
    """Test that repos with no commits return empty list."""
    mock_repo = Mock(spec=git.Repo)
    mock_repo.iter_commits.return_value = []
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path")

    assert edges == []


async def test_analyze_coupling_detects_coupled_files():
    """Test that files changing together create COUPLED_WITH edges."""
    # Mock repo with commits
    mock_repo = Mock(spec=git.Repo)

    # Create mock commits where file_a.py and file_b.py change together
    commits = []

    # Commit 1: file_a.py and file_b.py change together
    commit1 = Mock()
    commit1.hexsha = "abc123"
    commit1.parents = [Mock()]
    diff1_a = Mock()
    diff1_a.a_path = "src/file_a.py"
    diff1_a.b_path = "src/file_a.py"
    diff1_b = Mock()
    diff1_b.a_path = "src/file_b.py"
    diff1_b.b_path = "src/file_b.py"
    commit1.diff.return_value = [diff1_a, diff1_b]
    commits.append(commit1)

    # Commit 2: file_a.py and file_b.py change together again
    commit2 = Mock()
    commit2.hexsha = "def456"
    commit2.parents = [Mock()]
    diff2_a = Mock()
    diff2_a.a_path = "src/file_a.py"
    diff2_a.b_path = "src/file_a.py"
    diff2_b = Mock()
    diff2_b.a_path = "src/file_b.py"
    diff2_b.b_path = "src/file_b.py"
    commit2.diff.return_value = [diff2_a, diff2_b]
    commits.append(commit2)

    # Commit 3: only file_a.py changes
    commit3 = Mock()
    commit3.hexsha = "ghi789"
    commit3.parents = [Mock()]
    diff3 = Mock()
    diff3.a_path = "src/file_a.py"
    diff3.b_path = "src/file_a.py"
    commit3.diff.return_value = [diff3]
    commits.append(commit3)

    mock_repo.iter_commits.return_value = commits
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path", threshold=0.5)

    # file_a and file_b appear together 2 out of 3 times file_a appears
    # coupling_frequency = 2/3 = 0.667 > 0.5 threshold
    assert len(edges) == 1

    edge = edges[0]
    assert edge.from_id == _file_node_id("/fake/path", "src/file_a.py")
    assert edge.to_id == _file_node_id("/fake/path", "src/file_b.py")
    assert edge.kind == EdgeType.COUPLED_WITH
    assert edge.confidence >= 0.5
    assert "coupling_frequency" in edge.metadata
    assert "cooccurrence_count" in edge.metadata


async def test_analyze_coupling_threshold_filtering():
    """Test that threshold filters out low-coupling pairs."""
    mock_repo = Mock(spec=git.Repo)

    commits = []

    # file_a and file_b change together once
    commit1 = Mock()
    commit1.hexsha = "abc123"
    commit1.parents = [Mock()]
    diff1_a = Mock()
    diff1_a.a_path = "file_a.py"
    diff1_a.b_path = "file_a.py"
    diff1_b = Mock()
    diff1_b.a_path = "file_b.py"
    diff1_b.b_path = "file_b.py"
    commit1.diff.return_value = [diff1_a, diff1_b]
    commits.append(commit1)

    # file_a changes alone 9 more times
    for i in range(9):
        commit = Mock()
        commit.hexsha = f"commit{i}"
        commit.parents = [Mock()]
        diff = Mock()
        diff.a_path = "file_a.py"
        diff.b_path = "file_a.py"
        commit.diff.return_value = [diff]
        commits.append(commit)

    mock_repo.iter_commits.return_value = commits
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        # coupling_frequency = 1/10 = 0.1 < 0.3 threshold
        edges = await analyze_coupling("/fake/path", threshold=0.3)

    assert len(edges) == 0


async def test_analyze_coupling_initial_commit():
    """Test handling of initial commit (no parents)."""
    mock_repo = Mock(spec=git.Repo)

    # Initial commit with no parents
    commit = Mock()
    commit.hexsha = "initial"
    commit.parents = []

    # Mock tree traversal
    blob1 = Mock()
    blob1.type = "blob"
    blob1.path = "file_a.py"

    blob2 = Mock()
    blob2.type = "blob"
    blob2.path = "file_b.py"

    tree_mock = Mock()
    tree_mock.traverse.return_value = [blob1, blob2]
    commit.tree = tree_mock

    mock_repo.iter_commits.return_value = [commit]
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path", threshold=0.9)

    # Initial commit: both files appear together once (100% coupling)
    assert len(edges) == 1


async def test_analyze_coupling_handles_diff_errors():
    """Test that diff errors are handled gracefully."""
    mock_repo = Mock(spec=git.Repo)

    # Commit that throws error on diff
    commit1 = Mock()
    commit1.hexsha = "error123"
    commit1.parents = [Mock()]
    commit1.diff.side_effect = git.GitCommandError("diff", "error")

    # Valid commit
    commit2 = Mock()
    commit2.hexsha = "valid456"
    commit2.parents = [Mock()]
    diff = Mock()
    diff.a_path = "file_a.py"
    diff.b_path = "file_a.py"
    commit2.diff.return_value = [diff]

    mock_repo.iter_commits.return_value = [commit1, commit2]
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path")

    # Should handle error and continue
    assert isinstance(edges, list)


async def test_analyze_coupling_confidence_mapping():
    """Test that coupling frequency maps correctly to confidence."""
    mock_repo = Mock(spec=git.Repo)

    commits = []

    # Create 10 commits where file_a and file_b change together 7 times
    for i in range(7):
        commit = Mock()
        commit.hexsha = f"together{i}"
        commit.parents = [Mock()]
        diff_a = Mock()
        diff_a.a_path = "file_a.py"
        diff_a.b_path = "file_a.py"
        diff_b = Mock()
        diff_b.a_path = "file_b.py"
        diff_b.b_path = "file_b.py"
        commit.diff.return_value = [diff_a, diff_b]
        commits.append(commit)

    # file_a changes alone 3 times
    for i in range(3):
        commit = Mock()
        commit.hexsha = f"alone{i}"
        commit.parents = [Mock()]
        diff = Mock()
        diff.a_path = "file_a.py"
        diff.b_path = "file_a.py"
        commit.diff.return_value = [diff]
        commits.append(commit)

    mock_repo.iter_commits.return_value = commits
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path", threshold=0.3)

    # coupling_frequency = 7/10 = 0.7
    assert len(edges) == 1
    edge = edges[0]
    assert abs(edge.confidence - 0.7) < 0.01
    assert abs(edge.metadata["coupling_frequency"] - 0.7) < 0.01


async def test_analyze_coupling_multiple_file_pairs():
    """Test detection of multiple coupled pairs."""
    mock_repo = Mock(spec=git.Repo)

    commits = []

    # Commit 1: A, B, C change together
    commit1 = Mock()
    commit1.hexsha = "abc1"
    commit1.parents = [Mock()]
    commit1.diff.return_value = [
        Mock(a_path="A.py", b_path="A.py"),
        Mock(a_path="B.py", b_path="B.py"),
        Mock(a_path="C.py", b_path="C.py"),
    ]
    commits.append(commit1)

    # Commit 2: A, B, C change together again
    commit2 = Mock()
    commit2.hexsha = "abc2"
    commit2.parents = [Mock()]
    commit2.diff.return_value = [
        Mock(a_path="A.py", b_path="A.py"),
        Mock(a_path="B.py", b_path="B.py"),
        Mock(a_path="C.py", b_path="C.py"),
    ]
    commits.append(commit2)

    mock_repo.iter_commits.return_value = commits
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        edges = await analyze_coupling("/fake/path", threshold=0.9)

    # Should create edges for: A-B, A-C, B-C
    assert len(edges) == 3

    edge_pairs = {(e.from_id, e.to_id) for e in edges}
    assert (
        _file_node_id("/fake/path", "A.py"),
        _file_node_id("/fake/path", "B.py"),
    ) in edge_pairs
    assert (
        _file_node_id("/fake/path", "A.py"),
        _file_node_id("/fake/path", "C.py"),
    ) in edge_pairs
    assert (
        _file_node_id("/fake/path", "B.py"),
        _file_node_id("/fake/path", "C.py"),
    ) in edge_pairs


@pytest.mark.slow
async def test_analyze_coupling_performance():
    """Test that analysis completes in < 5s for 1000 commits."""
    mock_repo = Mock(spec=git.Repo)

    # Create 1000 mock commits with varying file changes
    commits = []
    for i in range(1000):
        commit = Mock()
        commit.hexsha = f"commit{i}"
        commit.parents = [Mock()]

        # Vary the files changed to simulate real repo
        diffs = []
        for j in range(i % 5 + 1):  # 1-5 files per commit
            diff = Mock()
            diff.a_path = f"file_{j % 20}.py"  # 20 different files
            diff.b_path = f"file_{j % 20}.py"
            diffs.append(diff)

        commit.diff.return_value = diffs
        commits.append(commit)

    mock_repo.iter_commits.return_value = commits
    mock_repo.working_tree_dir = "/fake/path"

    with patch("git.Repo", return_value=mock_repo):
        start = time.time()
        edges = await analyze_coupling("/fake/path", threshold=0.3)
        elapsed = time.time() - start

    assert elapsed < 5.0, f"Analysis took {elapsed:.2f}s, expected < 5s"
    assert isinstance(edges, list)
    assert len(edges) > 0  # Should find some coupling
