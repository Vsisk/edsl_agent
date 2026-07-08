from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


FailureReason = Literal[
    "NO_CANDIDATE",
    "NO_VALID_REFERENCE_NODE",
    "INVALID_TREE_JSON",
    "INVALID_TARGET_NODE",
    "LLM_RERANK_FAILED",
    "VALIDATION_FAILED",
]


class TreeReferenceResolveInput(BaseModel):
    target_node: dict[str, Any]
    query: str
    annotation: str | None = None
    tree_json: dict[str, Any]
    target_node_path: str | None = None
    expected_node_types: list[str] = Field(default_factory=list)
    max_candidates: int = 10
    debug: bool = False


class NodeIndexEntry(BaseModel):
    node_id: str
    json_path: str
    xml_path: str
    xml_name: str | None = None
    tree_node_type: str
    annotation: str | None = None
    edsl_semistruct_text: str = ""
    data_type: str | None = None
    expression: str | None = None
    parent_node_id: str | None = None
    parent_json_path: str | None = None
    ancestor_xml_names: list[str] = Field(default_factory=list)
    child_xml_names: list[str] = Field(default_factory=list)
    local_context_names: list[str] = Field(default_factory=list)
    iter_local_context_names: list[str] = Field(default_factory=list)
    data_source_summary: str | None = None
    ab_bo_name: str | None = None
    search_text: str = ""


class ReferenceSearchSpec(BaseModel):
    target_summary: str = ""
    target_keywords: list[str] = Field(default_factory=list)
    expected_node_types: list[str] = Field(default_factory=list)
    expected_data_types: list[str] = Field(default_factory=list)
    structural_constraints: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)


class CandidateEvidence(BaseModel):
    source: Literal["exact", "lexical", "structural", "embedding", "history", "llm", "fallback"]
    score: float = 0.0
    reason: str = ""


class TreeReferenceCandidate(BaseModel):
    node_id: str
    json_path: str
    xml_path: str | None = None
    xml_name: str | None = None
    tree_node_type: str
    annotation: str | None = None
    confidence: float = 0.0
    match_reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    raw_evidence: list[CandidateEvidence] = Field(default_factory=list)


class TreeReferenceResolveOutput(BaseModel):
    success: bool
    selected: TreeReferenceCandidate | None = None
    candidates: list[TreeReferenceCandidate] = Field(default_factory=list)
    failure_reason: FailureReason | None = None
    debug_info: dict[str, Any] | None = None
