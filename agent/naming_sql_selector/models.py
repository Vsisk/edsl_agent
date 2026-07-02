from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.context_manager.models import (
    ContextEvidenceItem,
    ContextRequirementHint,
    NamingSqlCandidate,
    NamingSqlSelectionConstraints,
)


class SelectorModel(BaseModel):
    """Legacy profile storage base retained until the resource cache is removed."""
    model_config = ConfigDict(extra="forbid")


class NamingSqlParamProfile(SelectorModel):
    name: str
    data_type: str = ""
    is_list: bool = False


class NamingSqlProfile(SelectorModel):
    site_id: str
    bo_name: str
    naming_sql_id: str
    sql_name: str
    label_name: str = ""
    sql_description: str = ""
    params: list[NamingSqlParamProfile] = Field(default_factory=list)
    filter_fields: list[str] = Field(default_factory=list)
    scope_tags: list[str] = Field(default_factory=list)
    is_full_table: bool = True
    search_text: str = ""


def _strict_copy(model_type: type[BaseModel], value: Any) -> BaseModel:
    raw_value = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return model_type.model_validate(raw_value, strict=True)


class NamingSqlSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

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
    model_config = ConfigDict(extra="forbid", strict=True)

    success: bool
    candidates: list[NamingSqlCandidate] = Field(default_factory=list)
    context_requirements_hint: list[ContextRequirementHint] = Field(default_factory=list)
    selection_constraints: NamingSqlSelectionConstraints | None = None
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)
    prompt_view: dict[str, Any] | None = None
    failure_reason: str | None = None

    @field_validator("candidates", mode="before")
    @classmethod
    def validate_candidates_strictly(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_strict_copy(NamingSqlCandidate, item) for item in value]
        return value

    @field_validator("context_requirements_hint", mode="before")
    @classmethod
    def validate_hints_strictly(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_strict_copy(ContextRequirementHint, item) for item in value]
        return value

    @field_validator("selection_constraints", mode="before")
    @classmethod
    def validate_constraints_strictly(cls, value: Any) -> Any:
        if value is None:
            return None
        return _strict_copy(NamingSqlSelectionConstraints, value)

    @field_validator("evidence_trace", mode="before")
    @classmethod
    def validate_evidence_strictly(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [_strict_copy(ContextEvidenceItem, item) for item in value]
        return value

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
