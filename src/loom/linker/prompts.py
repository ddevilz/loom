from __future__ import annotations


def llm_match_prompt(*, code_summary: str, doc_text: str) -> str:
    return (
        "You are linking code to documentation.\n"
        "Decide whether the code implements the requirement.\n\n"
        "Return STRICT JSON with keys: implements (bool), confidence (float 0-1), reason (string).\n\n"
        f"DOC:\n{doc_text}\n\n"
        f"CODE SUMMARY:\n{code_summary}\n"
    )
