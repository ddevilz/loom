from __future__ import annotations

from enum import Enum, StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EdgeType(StrEnum):
    # code → code
    CALLS = "calls"
    EXTENDS = "extends"
    # Placeholders — declared to keep EdgeTypeAdapter's storage map complete,
    # but no parser or linker produces these edges yet.
    IMPORTS = "imports"
    IMPLEMENTS = "implements"  # Java-style interface implementation
    USES_TYPE = "uses_type"
    MEMBER_OF = "member_of"
    STEP_IN = "step_in"
    COUPLED_WITH = "coupled_with"
    CONTAINS = "contains"

    # dynamic/reflection edges
    DYNAMIC_CALL = "dynamic_call"
    REFLECTS_CALL = "reflects_call"
    DYNAMIC_IMPORT = "dynamic_import"
    UNRESOLVED_CALL = "unresolved_call"

    # doc → doc
    CHILD_OF = "child_of"
    REFERENCES = "references"

    # cross-domain
    LOOM_IMPLEMENTS = "loom_implements"
    LOOM_VIOLATES = "loom_violates"


LinkMethod = Literal["embed_match", "git_commit", "ast_diff", "llm_match", "name_match"]


class EdgeOrigin(str, Enum):
    COMPUTED = "computed"
    NAME_MATCH = "name_match"
    EMBED_MATCH = "embed_match"
    LLM_MATCH = "llm_match"
    GIT_COMMIT = "git_commit"
    HUMAN = "human"


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    kind: EdgeType

    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    origin: EdgeOrigin = EdgeOrigin.COMPUTED

    link_method: LinkMethod | None = None
    link_reason: str | None = None

    @property
    def is_loom_edge(self) -> bool:
        return self.kind in {
            EdgeType.LOOM_IMPLEMENTS,
            EdgeType.LOOM_VIOLATES,
        }

    @model_validator(mode="after")
    def _validate_edge(self) -> Edge:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

        if self.is_loom_edge:
            # link_method/link_reason are optional, but if present must be coherent
            if self.link_method is None and self.link_reason is not None:
                raise ValueError("link_reason requires link_method for LOOM_* edges")
        else:
            if self.link_method is not None or self.link_reason is not None:
                raise ValueError(
                    "link_method/link_reason are only allowed for LOOM_* edges"
                )

        return self
