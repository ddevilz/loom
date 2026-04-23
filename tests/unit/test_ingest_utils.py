from __future__ import annotations

from pathlib import Path

from loom.ingest.utils import sha256_of_file


def test_sha256_of_file_stable(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello world")
    h1 = sha256_of_file(f)
    h2 = sha256_of_file(f)
    assert h1 == h2
    assert len(h1) == 64  # hex SHA-256


def test_sha256_of_file_differs_on_content_change(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello world")
    h1 = sha256_of_file(f)
    f.write_bytes(b"hello world!")
    h2 = sha256_of_file(f)
    assert h1 != h2


def test_sha256_of_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    h = sha256_of_file(f)
    assert len(h) == 64
