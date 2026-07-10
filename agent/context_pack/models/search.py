from typing import Any

from pydantic import Field

from .pack import Authority, ContextFact, RetrievalEvidence, SourceLocator, StrictModel


class SearchFilters(StrictModel):
    item_types: list[str] = Field(default_factory=list)
    expected_node_types: list[str] = Field(default_factory=list)


class SearchDocument(StrictModel):
    item_id: str
    source_id: str
    item_type: str
    search_text: str
    summary: str
    locator: SourceLocator
    authority: Authority
    content_hash: str
    content: dict[str, Any]
    facts: list[ContextFact] = Field(default_factory=list)


class SearchHit(StrictModel):
    document: SearchDocument
    rank: int = Field(ge=1)
    evidence: list[RetrievalEvidence] = Field(default_factory=list)


class SearchResult(StrictModel):
    hits: list[SearchHit] = Field(default_factory=list)
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)
