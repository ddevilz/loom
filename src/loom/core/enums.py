from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class SummarySource(StrEnum):
    AGENT = "AGENT"
    AUTO = "AUTO"


class QuestionType(StrEnum):
    DEAD_CODE       = "DEAD_CODE"
    BRIDGE_NODE     = "BRIDGE_NODE"
    MISSING_SUMMARY = "MISSING_SUMMARY"
    LOW_COHESION    = "LOW_COHESION"
