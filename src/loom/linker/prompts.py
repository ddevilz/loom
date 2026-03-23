from __future__ import annotations

_MAX_TEXT_LEN = 2000


def _truncate(text: str, max_len: int = _MAX_TEXT_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n[truncated]"


def llm_match_prompt(*, code_summary: str, doc_text: str) -> str:
    return (
        "You are linking code to documentation.\n"
        "Decide whether the code implements the requirement.\n\n"
        "Return STRICT JSON with keys: implements (bool), confidence (float 0-1), reason (string).\n\n"
        f"DOC:\n{_truncate(doc_text)}\n\n"
        f"CODE SUMMARY:\n{_truncate(code_summary)}\n"
    )


def drift_detection_prompt(*, code_summary: str, doc_text: str) -> str:
    return (
        "You are checking whether code behavior violates a requirement.\n"
        "Return STRICT JSON with keys: violates (bool), confidence (float 0-1), reason (string).\n\n"
        f"REQUIREMENT:\n{_truncate(doc_text)}\n\n"
        f"CODE SUMMARY:\n{_truncate(code_summary)}\n"
    )
