from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .assets import (
    ContextAsset,
    ContextEvidenceItem,
    ContextRequirementHint,
    NamingSqlCandidate,
    NamingSqlSelectionConstraints,
)
from .request import ContextChainType


class NamingSqlContextRequestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: str
    project_id: str
    chain_type: ContextChainType = "namingsql_selection"
    query: str
    json_path: str
    target_bo_name: str | None = None
    parent_bo_hint: str | None = None
    target_logic_area_id_list: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class GlobalContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)
    loaded_paths: list[str] = Field(default_factory=list)


class NodeContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_path: str
    node: dict[str, Any]
    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)
    current_node: dict[str, Any] = Field(default_factory=dict)
    parent_node: dict[str, Any] | None = None
    ancestors: list[dict[str, Any]] = Field(default_factory=list)
    sibling_summaries: list[dict[str, Any]] = Field(default_factory=list)
    visible_local_context: list[dict[str, Any]] = Field(default_factory=list)
    visible_iter_context: list[dict[str, Any]] = Field(default_factory=list)
    existing_data_source_ids: list[str] = Field(default_factory=list)
    existing_data_source: dict[str, Any] | None = None
    existing_bo_name: str | None = None
    existing_bo_ids: list[str] = Field(default_factory=list)
    existing_naming_sql_ids: list[str] = Field(default_factory=list)
    is_simple_leaf: bool = False
    simple_leaf_summary: dict[str, Any] | None = None
    fee_table_summary: dict[str, Any] | None = None


class LogicAreaContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic_area_ids: list[str] = Field(default_factory=list)
    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)
    sa_texts: list[str] = Field(default_factory=list)
    se_texts: list[str] = Field(default_factory=list)
    cbs_terms: list[str] = Field(default_factory=list)
    fee_category_summaries: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[Any] = Field(default_factory=list)
    samples: list[Any] = Field(default_factory=list)


class ProjectSearchContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class NamingSqlResourceCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[NamingSqlCandidate] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class ReferenceCaseCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: ContextAsset
    candidate: NamingSqlCandidate | None = None
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class ReferenceCaseBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[ReferenceCaseCandidate] = Field(default_factory=list)
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)


class NamingSqlSelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: NamingSqlContextRequestSummary
    global_context: GlobalContextBlock
    node_context: NodeContextBlock
    logic_area_context: LogicAreaContextBlock | None = None
    project_search_context: ProjectSearchContextBlock | None = None
    resource_candidates: NamingSqlResourceCandidates
    ootb_reference_cases: ReferenceCaseBlock = Field(default_factory=ReferenceCaseBlock)
    site_knowledge_cases: ReferenceCaseBlock = Field(default_factory=ReferenceCaseBlock)
    history_cases: ReferenceCaseBlock = Field(default_factory=ReferenceCaseBlock)
    requirement_hints: list[ContextRequirementHint] = Field(default_factory=list)
    constraints: NamingSqlSelectionConstraints = Field(
        default_factory=NamingSqlSelectionConstraints
    )
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)
    prompt_view: dict | None = None
