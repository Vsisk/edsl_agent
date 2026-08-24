from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ResourceType = Literal["context", "function", "bo", "naming_sql"]
LogicRequirementType = Literal[
    "value_source",
    "condition",
    "merge",
    "filter",
    "aggregation",
    "conditional_source",
]
ScopeType = Literal["acct", "sub", "unknown"]
CardinalityType = Literal["single", "list", "unknown"]
SourceType = Literal["context", "function", "bo", "naming_sql", "literal"]


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_name: str
    concept_type: str | None = None
    scope: ScopeType
    cardinality: CardinalityType


class LogicRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    type: LogicRequirementType
    semantic: str
    inputs: list[str] = Field(default_factory=list)


class SpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetSpec
    logic_requirements: list[LogicRequirement]
    known_values: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    requirement_id: str
    resource_types: list[ResourceType]
    keywords: list[str]
    semantic: str
    scope: str | None = None
    expected_return_type: str | None = None
    expected_cardinality: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    introduced_by: dict[str, Any] | None = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    success: bool
    selected_resource: dict[str, Any] | None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None


class MissingRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    semantic: str
    resource_types: list[ResourceType]
    expected_return_type: str | None = None
    expected_cardinality: str | None = None
    scope: str | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    introduced_by: dict[str, Any] | None = None


class ResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    resource_id: str | None
    params: dict[str, Any] = Field(default_factory=dict)
    return_field: str | None = None
    cardinality: str | None = None


class ExpressionContextSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: TargetSpec
    logic_requirements: list[LogicRequirement]
    resources: dict[str, ResourceBinding] = Field(default_factory=dict)


class SpecGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed: bool
    spec: ExpressionContextSpec | None = None
    missing_requirements: list[MissingRequirement] = Field(default_factory=list)
    resolved_values: dict[str, Any] = Field(default_factory=dict)


class GenerateSpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    query: str
    node: Any
    node_path: str = ""
    bill_type: str | None = None
