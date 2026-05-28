"""Unit tests for ChangeReport and IncrementalSync.

Tests the three-tier change detection: mtime → SHA-256 → re-index.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from loom.graph.db import DB
from loom.graph.repository import Repository
from loom.graph.repository.fingerprints import FileFingerprint
from loom.indexer.incremental import ChangeReport, IncrementalSync
from loom.indexer.utils import sha256_of_file


@pytest.fixture
def db(tmp_path: Path) -> DB:
    return DB(path=tmp_path / "loom.db")


@pytest.fixture
def repo(db: DB) -> Repository:
    return Repository(db)


@pytest.fixture
def sync(repo: Repository) -> IncrementalSync:
    return IncrementalSync(repo)


# ---------------------------------------------------------------------------
# Test 1: New file — not in fingerprint store
# ---------------------------------------------------------------------------

def test_new_file_goes_to_new_and_files_to_index(sync: IncrementalSync, tmp_path: Path) -> None:
    """A file with no stored fingerprint appears in report.new and files_to_index."""
    f = tmp_path / "new_file.py"
    f.write_text("def hello(): pass\n")

    report = sync.classify_changes([str(f)])

    assert str(f) in report.new
    assert str(f) in report.files_to_index
    assert str(f) not in report.unchanged
    assert str(f) not in report.mtime_only
    assert str(f) not in report.changed


# ---------------------------------------------------------------------------
# Test 2: Unchanged — same mtime in store
# ---------------------------------------------------------------------------

def test_unchanged_when_mtime_matches(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """A file whose stored mtime matches the filesystem appears in report.unchanged."""
    f = tmp_path / "stable.py"
    f.write_text("x = 1\n")

    mtime_ns = os.stat(str(f)).st_mtime_ns
    sha = sha256_of_file(f)
    repo.fingerprints.upsert([FileFingerprint(str(f), sha, mtime_ns, time.time())])

    report = sync.classify_changes([str(f)])

    assert str(f) in report.unchanged
    assert str(f) not in report.files_to_index
    assert str(f) not in report.new
    assert str(f) not in report.mtime_only
    assert str(f) not in report.changed


# ---------------------------------------------------------------------------
# Test 3: mtime_only — mtime changed but SHA-256 unchanged
# ---------------------------------------------------------------------------

def test_mtime_only_when_content_unchanged(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """When mtime changes but content is the same, file goes to mtime_only, NOT files_to_index."""
    f = tmp_path / "touched.py"
    f.write_text("y = 2\n")

    sha = sha256_of_file(f)
    original_mtime_ns = os.stat(str(f)).st_mtime_ns

    # Store the fingerprint with the current mtime
    repo.fingerprints.upsert([FileFingerprint(str(f), sha, original_mtime_ns, time.time())])

    # Touch the file to advance its mtime without changing content
    # Use os.utime with a 1-second offset to guarantee mtime change
    new_mtime_s = os.stat(str(f)).st_mtime + 1.0
    os.utime(str(f), (new_mtime_s, new_mtime_s))

    new_mtime_ns = os.stat(str(f)).st_mtime_ns
    assert new_mtime_ns != original_mtime_ns, "mtime must have changed for this test to be valid"

    report = sync.classify_changes([str(f)])

    assert str(f) in report.mtime_only
    assert str(f) not in report.files_to_index
    assert str(f) not in report.new
    assert str(f) not in report.unchanged
    assert str(f) not in report.changed


# ---------------------------------------------------------------------------
# Test 4: Changed — mtime AND SHA-256 both differ
# ---------------------------------------------------------------------------

def test_changed_when_mtime_and_sha_differ(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """When both mtime and content change, file goes to report.changed and files_to_index."""
    f = tmp_path / "edited.py"
    f.write_text("z = 3\n")

    old_sha = sha256_of_file(f)
    old_mtime_ns = os.stat(str(f)).st_mtime_ns
    repo.fingerprints.upsert([FileFingerprint(str(f), old_sha, old_mtime_ns, time.time())])

    # Rewrite with different content; sleep briefly to guarantee new mtime
    f.write_text("z = 999\n")
    # Ensure mtime is actually different by bumping it explicitly
    new_mtime_s = os.stat(str(f)).st_mtime + 1.0
    os.utime(str(f), (new_mtime_s, new_mtime_s))

    assert sha256_of_file(f) != old_sha, "SHA must differ for this test to be valid"
    assert os.stat(str(f)).st_mtime_ns != old_mtime_ns, "mtime must differ"

    report = sync.classify_changes([str(f)])

    assert str(f) in report.changed
    assert str(f) in report.files_to_index
    assert str(f) not in report.new
    assert str(f) not in report.unchanged
    assert str(f) not in report.mtime_only


# ---------------------------------------------------------------------------
# Test 5: Deleted — file in store but not in discovered list
# ---------------------------------------------------------------------------

def test_deleted_when_file_not_in_discovered(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """A file in the fingerprint store but absent from discovered_files appears in report.deleted."""
    ghost_path = str(tmp_path / "ghost.py")
    repo.fingerprints.upsert([FileFingerprint(ghost_path, "deadbeef", 12345, time.time())])

    # Discover a different (real) file
    real = tmp_path / "real.py"
    real.write_text("pass\n")

    report = sync.classify_changes([str(real)])

    assert ghost_path in report.deleted
    assert str(real) not in report.deleted


# ---------------------------------------------------------------------------
# Test 6: files_to_index = new + changed, excludes mtime_only and unchanged
# ---------------------------------------------------------------------------

def test_files_to_index_is_new_plus_changed(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """files_to_index contains exactly new + changed, nothing else."""
    # New file
    f_new = tmp_path / "new.py"
    f_new.write_text("def new(): pass\n")

    # Unchanged file
    f_unchanged = tmp_path / "unchanged.py"
    f_unchanged.write_text("def old(): pass\n")
    mtime_ns = os.stat(str(f_unchanged)).st_mtime_ns
    sha = sha256_of_file(f_unchanged)
    repo.fingerprints.upsert([FileFingerprint(str(f_unchanged), sha, mtime_ns, time.time())])

    # mtime_only file
    f_mtime = tmp_path / "mtime_only.py"
    f_mtime.write_text("x = 1\n")
    sha_m = sha256_of_file(f_mtime)
    mtime_m = os.stat(str(f_mtime)).st_mtime_ns
    repo.fingerprints.upsert([FileFingerprint(str(f_mtime), sha_m, mtime_m, time.time())])
    s = os.stat(str(f_mtime))
    os.utime(str(f_mtime), (s.st_mtime + 1.0, s.st_mtime + 1.0))

    # Changed file
    f_changed = tmp_path / "changed.py"
    f_changed.write_text("def original(): pass\n")
    old_sha = sha256_of_file(f_changed)
    old_mtime_ns = os.stat(str(f_changed)).st_mtime_ns
    repo.fingerprints.upsert([FileFingerprint(str(f_changed), old_sha, old_mtime_ns, time.time())])
    f_changed.write_text("def modified(): pass\n")
    s = os.stat(str(f_changed))
    os.utime(str(f_changed), (s.st_mtime + 1.0, s.st_mtime + 1.0))

    discovered = [str(f_new), str(f_unchanged), str(f_mtime), str(f_changed)]
    report = sync.classify_changes(discovered)

    to_index = set(report.files_to_index)
    assert str(f_new) in to_index
    assert str(f_changed) in to_index
    assert str(f_unchanged) not in to_index
    assert str(f_mtime) not in to_index
    # Exactly new + changed — no extras
    assert len(to_index) == 2


# ---------------------------------------------------------------------------
# Test 7: Empty discovered list with stored fingerprints → all in deleted
# ---------------------------------------------------------------------------

def test_empty_discovered_puts_all_stored_in_deleted(sync: IncrementalSync, repo: Repository, tmp_path: Path) -> None:
    """When discovered_files is empty, every stored fingerprint appears in report.deleted."""
    paths = [str(tmp_path / f"file{i}.py") for i in range(3)]
    fps = [FileFingerprint(p, f"sha{i}", i * 1000, time.time()) for i, p in enumerate(paths)]
    repo.fingerprints.upsert(fps)

    report = sync.classify_changes([])

    assert report.new == []
    assert report.changed == []
    assert report.mtime_only == []
    assert report.unchanged == []
    assert set(report.deleted) == set(paths)


# ---------------------------------------------------------------------------
# Test 8: Vanished file — discovered then deleted before stat (TOCTOU race)
# ---------------------------------------------------------------------------

def test_vanished_file_goes_to_deleted(sync: IncrementalSync, tmp_path: Path) -> None:
    """File discovered by walk then deleted before stat → treated as deleted, no crash."""
    vanished = tmp_path / "gone.py"
    vanished.write_text("pass\n")
    vanished.unlink()  # delete before classify_changes runs

    report = sync.classify_changes([str(vanished)])
    assert str(vanished) in report.deleted
