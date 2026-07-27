from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.resource_manager.loader.registry_models import ReturnType


class GoalRole(str, Enum):
    FINAL_OUTPUT = "final_output"
    LOOKUP_KEY = "lookup_key"
    QUERY_PARAM = "query_param"
    FILTER_VALUE = "filter_value"
    FUNCTION_PARAM = "function_param"
    INTERMEDIATE_VALUE = "intermediate_value"


class GoalStatus(str, Enum):
    PENDING = "pending"
    SEARCHING = "searching"
    WAITING_DEPENDENCIES = "waiting_dependencies"
    RESOLVED = "resolved"
    FAILED = "failed"


class ResourceTier(str, Enum):
    VISIBLE_VALUE = "visible_value"
    BO_FIELD = "bo_field"
    BO_ACCESS = "bo_access"
    FUNCTION = "function"
    FALLBACK = "fallback"


RESOURCE_TIER_ORDER = (
    ResourceTier.VISIBLE_VALUE,
    ResourceTier.BO_FIELD,
    ResourceTier.BO_ACCESS,
    ResourceTier.FUNCTION,
    ResourceTier.FALLBACK,
)


class CoverageKind(str, Enum):
    DIRECT_COVER = "direct_cover"
    DEPENDENCY_COVER = "dependency_cover"
    NOT_COVER = "not_cover"


class ResourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    return_type: ReturnType


class ResourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    candidate_id: str
    kind: str
    resource: Any
    return_type: ReturnType
    required_inputs: list[ResourceInput] = Field(default_factory=list)
    bo_name: str | None = None
    field_name: str | None = None
    is_key: bool = False
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ValueGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    semantic_name: str
    role: GoalRole
    expected_type: ReturnType
    status: GoalStatus = GoalStatus.PENDING
    current_tier: ResourceTier = ResourceTier.VISIBLE_VALUE
    target_bo_name: str | None = None
    target_field_name: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    candidate_resolutions: list[ResourceCandidate] = Field(default_factory=list)
    selected_candidate_id: str | None = None


class GoalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: ValueGoal
    tier: ResourceTier
    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    target_bo_name: str | None = None
    node_path: str = ""
    limit: int = Field(default=10, ge=1, le=30)


class CoverageDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CoverageKind
    selected_candidate_id: str | None = None
    target_field_name: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    continue_search: bool = False
    reason: str

    @model_validator(mode="after")
    def validate_candidate_reference(self) -> "CoverageDecision":
        if self.kind == CoverageKind.NOT_COVER and self.selected_candidate_id is not None:
            raise ValueError("not_cover cannot select a candidate")
        if self.kind != CoverageKind.NOT_COVER and not self.selected_candidate_id:
            raise ValueError("cover decision requires a selected candidate")
        return self


class ResolvedGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: ValueGoal
    candidate: ResourceCandidate
    dependencies: list["ResolvedGoal"] = Field(default_factory=list)
    bindings: dict[str, str] = Field(default_factory=dict)


class SpecOrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    query: str
    root_goal: ValueGoal
    root_resolution: ResolvedGoal | None = None
    execution_order: list[str] = Field(default_factory=list)
    failed_goal_ids: list[str] = Field(default_factory=list)
    resolution_trace: list[dict[str, Any]] = Field(default_factory=list)
