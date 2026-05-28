# tests/unit/test_mcp_enums.py
from __future__ import annotations


def test_error_code_values_are_all_caps() -> None:
    from loom.server.enums import ErrorCode

    assert ErrorCode.NODE_NOT_FOUND == "NODE_NOT_FOUND"
    assert ErrorCode.MISSING_ARGS == "MISSING_ARGS"
    assert ErrorCode.SESSION_NOT_FOUND == "SESSION_NOT_FOUND"
    assert ErrorCode.NO_PRIOR_SESSION == "NO_PRIOR_SESSION"
    assert ErrorCode.VALIDATION_ERROR == "VALIDATION_ERROR"


def test_error_code_is_str() -> None:
    from loom.server.enums import ErrorCode

    assert isinstance(ErrorCode.NODE_NOT_FOUND, str)
