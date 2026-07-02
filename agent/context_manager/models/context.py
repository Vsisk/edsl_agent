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


class NodeContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_path: str
    node: dict[str, Any]
    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class LogicAreaContextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic_area_ids: list[str] = Field(default_factory=list)
    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


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
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


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
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)
    prompt_view: str | None = None
