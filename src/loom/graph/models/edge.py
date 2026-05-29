from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeType(StrEnum):
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"
    COUPLED_WITH = "COUPLED_WITH"
    TESTED_BY = "TESTED_BY"


class ConfidenceTier(StrEnum):
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    kind: EdgeType

    confidence: float = 1.0
    confidence_tier: ConfidenceTier = ConfidenceTier.EXTRACTED
    metadata: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None

    @model_validator(mode="after")
    def _validate_edge(self) -> Edge:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return self
