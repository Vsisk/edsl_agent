from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.context_manager.models import (
    ContextEvidenceItem,
    ContextRequirementHint,
    NamingSqlCandidate,
    NamingSqlSelectionConstraints,
)


class NamingSqlSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    project_id: str
    query: str
    node: dict[str, Any]
    json_path: str
    target_bo_name: str | None = None
    parent_bo_hint: str | None = None
    target_logic_area_id_list: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)
    debug: bool = False


class NamingSqlSelectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    candidates: list[NamingSqlCandidate] = Field(default_factory=list)
    hints: list[ContextRequirementHint] = Field(default_factory=list)
    constraints: NamingSqlSelectionConstraints | None = None
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)
    prompt_view: dict[str, Any] | None = None
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "NamingSqlSelectResponse":
        if self.success:
            if not self.candidates:
                raise ValueError("successful selection requires at least one candidate")
            if self.failure_reason is not None:
                raise ValueError("successful selection cannot have a failure reason")
        else:
            if self.candidates:
                raise ValueError("failed selection cannot have candidates")
            if not self.failure_reason:
                raise ValueError("failed selection requires a failure reason")
            if self.prompt_view is not None:
                raise ValueError("failed selection cannot expose prompt internals")
        return self
