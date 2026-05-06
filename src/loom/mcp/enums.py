from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class ErrorCode(StrEnum):
    NODE_NOT_FOUND    = "NODE_NOT_FOUND"
    MISSING_ARGS      = "MISSING_ARGS"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    NO_PRIOR_SESSION  = "NO_PRIOR_SESSION"
    VALIDATION_ERROR  = "VALIDATION_ERROR"
