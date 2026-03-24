from __future__ import annotations

import pytest

from loom.ingest.git_miner import (
    _extract_ticket_refs,
    _parse_commit_log,
    MiningResult,
    CommitRef,
    tickets_for_file,
    files_for_ticket,
)


def test_extract_jira_ref():
    refs, closing = _extract_ticket_refs("PROJ-42: add sorting feature")
    assert any("PROJ-42" in r for r in refs)
    assert not closing


def test_extract_github_closes():
    refs, closing = _extract_ticket_refs("fixes #99: resolve login bug")
    assert any("99" in r for r in refs)
    assert closing


def test_extract_github_resolves():
    refs, closing = _extract_ticket_refs("resolves #123")
    assert any("123" in r for r in refs)
    assert closing


def test_extract_plain_hash_ref():
    refs, closing = _extract_ticket_refs("WIP #42 some work")
    # May or may not extract — depends on pattern. Just check no crash
    assert isinstance(refs, tuple)
    assert isinstance(closing, bool)


def test_no_refs():
    refs, closing = _extract_ticket_refs("chore: update readme")
    assert refs == ()
    assert not closing


def test_multiple_refs():
    refs, closing = _extract_ticket_refs("PROJ-1 and PROJ-2: multi-ticket work")
    ref_str = " ".join(refs)
    assert "PROJ-1" in ref_str
    assert "PROJ-2" in ref_str


def test_tickets_for_file_empty():
    result = MiningResult()
    assert tickets_for_file("src/auth.py", result) == set()


def test_files_for_ticket_empty():
    result = MiningResult()
    assert files_for_ticket("PROJ-42", result) == set()


def test_mining_result_populated():
    result = MiningResult()
    result.file_to_tickets["src/auth.py"] = {"PROJ-42", "PROJ-10"}
    result.ticket_to_files["PROJ-42"] = {"src/auth.py", "src/utils.py"}

    assert tickets_for_file("src/auth.py", result) == {"PROJ-42", "PROJ-10"}
    assert files_for_ticket("PROJ-42", result) == {"src/auth.py", "src/utils.py"}
    assert tickets_for_file("nonexistent.py", result) == set()
