from __future__ import annotations

from enum import Enum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeType(StrEnum):
    """Relationship types connecting graph nodes."""

    # Code → Code relationships
    CALLS = "calls"
    IMPORTS = "imports"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    USES_TYPE = "uses_type"
    MEMBER_OF = "member_of"
    STEP_IN = "step_in"
    COUPLED_WITH = "coupled_with"
    CONTAINS = "contains"

    # Dynamic/reflection edges
    DYNAMIC_CALL = "dynamic_call"
    REFLECTS_CALL = "reflects_call"
    DYNAMIC_IMPORT = "dynamic_import"
    UNRESOLVED_CALL = "unresolved_call"

    # Doc → Doc relationships
    CHILD_OF = "child_of"
    REFERENCES = "references"

    # Cross-domain relationships
    LOOM_IMPLEMENTS = "loom_implements"
    LOOM_SPECIFIES = "loom_specifies"
    LOOM_VIOLATES = "loom_violates"


LinkMethod = Literal["name_match", "embed_match", "llm_match", "ast_diff"]


class EdgeOrigin(str, Enum):
    """Origin/source of an edge relationship."""

    COMPUTED = "computed"
    NAME_MATCH = "name_match"
    EMBED_MATCH = "embed_match"
    LLM_MATCH = "llm_match"
    HUMAN = "human"


class Edge(BaseModel):
    """A directed edge in the knowledge graph.

    This is a pure data model with no behavior. All operations on edges
    should be in graph.py or other operation modules.
    """

    model_config = ConfigDict(extra="forbid")

    # Core identity
    from_id: str
    to_id: str
    kind: EdgeType

    # Edge metadata
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    origin: EdgeOrigin = EdgeOrigin.COMPUTED

    # Linking metadata (for LOOM_* edges)
    link_method: LinkMethod | None = None
    link_reason: str | None = None

    @property
    def is_loom_edge(self) -> bool:
        """True if this is a cross-domain LOOM edge."""
        return self.kind in {
            EdgeType.LOOM_IMPLEMENTS,
            EdgeType.LOOM_SPECIFIES,
            EdgeType.LOOM_VIOLATES,
        }

    @model_validator(mode="after")
    def _validate_edge(self) -> Edge:
        """Validate edge constraints."""
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

        if self.is_loom_edge:
            if self.link_method is None and self.link_reason is not None:
                raise ValueError("link_reason requires link_method for LOOM_* edges")
        else:
            if self.link_method is not None or self.link_reason is not None:
                raise ValueError(
                    "link_method/link_reason are only allowed for LOOM_* edges"
                )

        return self
