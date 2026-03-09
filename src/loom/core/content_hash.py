from __future__ import annotations

import hashlib


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash_for_line_span(
    src: bytes, start_line: int | None, end_line: int | None
) -> str:
    if start_line is None or end_line is None:
        return content_hash_bytes(src)

    lines = src.splitlines(keepends=True)
    start = max(0, start_line - 1)
    end = max(start, end_line)
    span = b"".join(lines[start:end])
    return content_hash_bytes(span)
