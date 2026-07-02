from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContextEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    action: str
    asset_id: str | None = None
    evidence: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ContextAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_type: Literal[
        "global_rule",
        "chain_rule",
        "edsl_node",
        "logic_area",
        "global_context",
        "local_context",
        "iter_context",
        "bo",
        "bo_field",
        "naming_sql",
        "function",
        "ootb_case",
        "site_knowledge",
        "history_case",
    ]
    scope: Literal["global", "site", "project", "logic_area", "node", "task"]
    site_id: str | None = None
    project_id: str | None = None
    logic_area_id: str | None = None
    json_path: str | None = None
    content: dict[str, Any]
    index_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    version: str | None = None


class NamingSqlCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    bo_name: str
    naming_sql_id: str
    naming_sql_name: str | None = None
    annotation: str = ""
    param_list: list[dict] = Field(default_factory=list)
    return_type: dict | None = None
    source: Literal[
        "resource_registry",
        "current_project",
        "ootb_reference",
        "site_knowledge",
        "history_case",
    ]
    rank: int
    evidence: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)


class ContextRequirementHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_name: str
    expected_data_type: str | None = None
    expected_data_type_name: str | None = None
    source_hint: str | None = None
    bind_to_candidates: list[str] = Field(default_factory=list)
    candidate_context_paths: list[str] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class NamingSqlSelectionConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_bo_names: list[str] = Field(default_factory=list)
    allowed_naming_sql_ids: list[str] = Field(default_factory=list)
    max_candidates: int = Field(default=5, ge=1)
