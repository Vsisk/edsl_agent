from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .request import ResourceName


class PackStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class SectionStatus(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    ERROR = "error"


class Authority(str, Enum):
    AUTHORITATIVE = "authoritative"
    NORMATIVE = "normative"
    REFERENCE = "reference"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocator(StrictModel):
    source_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_version: str | None = None
    path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class RetrievalEvidence(StrictModel):
    source: str
    action: str
    reason: str
    score: float | None = None
    match_kind: str | None = None


class ContextFact(StrictModel):
    key: str = Field(min_length=1)
    value: Any
    data_type: str | None = None


class ContextItem(StrictModel):
    item_id: str = Field(min_length=1)
    resource_name: ResourceName
    item_type: str = Field(min_length=1)
    authority: Authority
    content: dict[str, Any]
    summary: str
    locator: SourceLocator
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
    content_hash: str = Field(min_length=1)
    facts: list[ContextFact] = Field(default_factory=list)
    rank: int = Field(default=0, ge=0)


class BudgetUsage(StrictModel):
    item_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    trimmed_count: int = Field(default=0, ge=0)


class ContextWarning(StrictModel):
    code: str
    message: str = ""


class ContextTraceItem(StrictModel):
    source: str
    action: str
    detail: str = ""
    item_id: str | None = None


class ContextSection(StrictModel):
    resource_name: ResourceName
    status: SectionStatus
    items: list[ContextItem] = Field(default_factory=list)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[ContextWarning] = Field(default_factory=list)


class ContextConflict(StrictModel):
    fact_key: str
    item_ids: list[str]
    resolution: str
    values: list[Any] = Field(default_factory=list)


class ContextPack(StrictModel):
    status: PackStatus
    request_summary: dict[str, Any]
    current_node: dict[str, Any]
    sections: list[ContextSection] = Field(default_factory=list)
    conflicts: list[ContextConflict] = Field(default_factory=list)
    warnings: list[ContextWarning] = Field(default_factory=list)
    trace: list[ContextTraceItem] = Field(default_factory=list)
