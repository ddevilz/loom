from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeType(StrEnum):
    CALLS = "calls"
    CONTAINS = "contains"
    COUPLED_WITH = "coupled_with"


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

    @model_validator(mode="after")
    def _validate_edge(self) -> Edge:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return self
