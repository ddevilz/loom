"""Unit tests for FingerprintRepository."""
import time
import pytest
from loom.graph.db import DB
from loom.graph.repository.fingerprints import FileFingerprint, FingerprintRepository


@pytest.fixture
def repo(tmp_path):
    db = DB(tmp_path / "test.db")
    return FingerprintRepository(db)


def test_get_all_empty(repo):
    assert repo.get_all() == {}


def test_upsert_and_get(repo):
    fp = FileFingerprint("src/foo.py", "abc123", 1000, time.time())
    repo.upsert([fp])
    result = repo.get_all()
    assert "src/foo.py" in result
    assert result["src/foo.py"].content_sha == "abc123"


def test_upsert_updates_existing(repo):
    fp1 = FileFingerprint("src/foo.py", "abc", 1000, time.time())
    fp2 = FileFingerprint("src/foo.py", "xyz", 2000, time.time())
    repo.upsert([fp1])
    repo.upsert([fp2])
    result = repo.get_all()
    assert result["src/foo.py"].content_sha == "xyz"
    assert result["src/foo.py"].mtime_ns == 2000


def test_delete_paths(repo):
    fp = FileFingerprint("src/foo.py", "abc", 1000, time.time())
    repo.upsert([fp])
    repo.delete_paths(["src/foo.py"])
    assert repo.get_all() == {}


def test_delete_paths_empty_list(repo):
    repo.delete_paths([])  # Should not raise


def test_update_mtime(repo):
    fp = FileFingerprint("src/foo.py", "abc", 1000, time.time())
    repo.upsert([fp])
    repo.update_mtime("src/foo.py", 9999)
    result = repo.get_all()
    assert result["src/foo.py"].mtime_ns == 9999
    assert result["src/foo.py"].content_sha == "abc"  # unchanged
