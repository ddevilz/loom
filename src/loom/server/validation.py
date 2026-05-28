"""validation.py — request validation helpers and response constructors."""
from __future__ import annotations

from .enums import Confidence, ConfidenceSignal, ErrorCode

MAX_QUERY = 1000
MAX_ID = 512


def clamp_limit(n: int) -> int:
    return max(1, min(n, 100))


def clamp_depth(d: int) -> int:
    return max(1, min(d, 10))


def validate_text(value: str, *, field: str, max_length: int) -> str:
    v = value.strip()
    if not v:
        raise ValueError(f"{field} must be non-empty")
    if len(v) > max_length:
        raise ValueError(f"{field} must be <= {max_length} characters")
    return v


def ok(data: object) -> dict:
    return {"ok": True, "data": data}


def err(error_code: ErrorCode, message: str, suggestion: str | None = None) -> dict:
    result: dict = {"ok": False, "error_code": error_code, "message": message}
    if suggestion is not None:
        result["suggestion"] = suggestion
    return result


def compute_confidence(
    query: str,
    node_name: str,
    node_path: str,
    score: float,
    max_score: float,
    has_agent_summary: bool,
    caller_count: int,
) -> tuple[Confidence, list[ConfidenceSignal]]:
    signals: list[ConfidenceSignal] = []
    composite = 0.0
    if query.lower() == node_name.lower():
        composite += 0.40
        signals.append(ConfidenceSignal.EXACT_NAME_MATCH)
    norm_bm25 = (score / max_score) if max_score > 0 else 0.0
    composite += 0.25 * norm_bm25
    if norm_bm25 >= 0.7:
        signals.append(ConfidenceSignal.HIGH_BM25)
    if has_agent_summary:
        composite += 0.15
        signals.append(ConfidenceSignal.HAS_AGENT_SUMMARY)
    if caller_count > 5:
        composite += 0.12
        signals.append(ConfidenceSignal.HOT_NODE)
    if query.lower() in node_path.lower():
        composite += 0.08
        signals.append(ConfidenceSignal.PATH_MATCH)
    if composite >= 0.65:
        return Confidence.HIGH, signals
    if composite >= 0.35:
        return Confidence.MEDIUM, signals
    return Confidence.LOW, signals
