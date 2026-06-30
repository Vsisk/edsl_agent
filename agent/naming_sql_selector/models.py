from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SelectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AvailableValue(SelectorModel):
    name: str
    source_ref: str
    data_type: str = ""
    semantic_tags: list[str] = Field(default_factory=list)


class DataAccessSpec(SelectorModel):
    requires_naming_sql: bool = False
    business_terms: list[str] = Field(default_factory=list)
    scope_terms: list[str] = Field(default_factory=list)
    bo_hints: list[str] = Field(default_factory=list)
    filter_requirements: list[str] = Field(default_factory=list)
    available_values: list[AvailableValue] = Field(default_factory=list)
    allow_full_table: bool = False


class NamingSqlSelectionRequest(SelectorModel):
    site_id: str
    query: str
    node: dict = Field(default_factory=dict)
    parent_node: dict | None = None
    structured_spec: dict = Field(default_factory=dict)
    bo_name: str | None = None
    available_context: list[dict] = Field(default_factory=list)


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


class BoCandidate(SelectorModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bo_name: str
    score: float
    summary: str


class BoResolution(SelectorModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bo_name: str
    review_mode: Literal["llm", "deterministic_fallback", "not_required"]
    reasons: list[str] = Field(default_factory=list)


class SelectionOutputModel(SelectorModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ParamBinding(SelectionOutputModel):
    param_name: str
    source_ref: str
    confidence: float
    reason: str


class ParamBindingPlan(SelectionOutputModel):
    bindings: list[ParamBinding] = Field(default_factory=list)
    unbound_params: list[str] = Field(default_factory=list)
    ambiguous_params: list[str] = Field(default_factory=list)
    is_complete: bool = False


class SelectedNamingSql(SelectionOutputModel):
    naming_sql_id: str
    sql_name: str
    score: float
    binding_plan: ParamBindingPlan
    reasons: list[str] = Field(default_factory=list)


class RejectedNamingSql(SelectionOutputModel):
    naming_sql_id: str
    sql_name: str
    reject_codes: list[str]


class FallbackNamingSql(SelectionOutputModel):
    naming_sql_id: str
    sql_name: str
    reason: str = "FULL_TABLE_FALLBACK_ONLY"


class NamingSqlReviewCandidate(SelectionOutputModel):
    naming_sql_id: str
    sql_name: str
    score: float
    reasons: list[str] = Field(default_factory=list)


class NamingSqlSelectionResult(SelectionOutputModel):
    status: Literal["selected", "needs_review"]
    selected_bo: str
    selected: SelectedNamingSql | None = None
    fallback_candidates: list[FallbackNamingSql] = Field(default_factory=list)
    rejected_candidates: list[RejectedNamingSql] = Field(default_factory=list)
    review_mode: Literal["llm", "deterministic_fallback", "not_required"]
