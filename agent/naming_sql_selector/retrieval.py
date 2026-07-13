from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.context_manager.errors import ContextBuildError, INVALID_LLM_OUTPUT, NO_NAMING_SQL_CANDIDATES
from agent.context_manager.models import ContextAsset, ContextEvidenceItem, NamingSqlCandidate
from agent.context_manager.resolvers.resource import ResourceAssetBuilder
from agent.resource_manager.loader.resource_loader import LoadedResource

from .context_adapter import NamingSqlSelectionContext


class NamingSqlRetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[NamingSqlCandidate] = Field(default_factory=list)
    assets: list[ContextAsset] = Field(default_factory=list)
    evidence: list[ContextEvidenceItem] = Field(default_factory=list)


class NamingSqlCandidateRetriever:
    def __init__(self, *, hybrid_retriever: Any = None,
                 asset_builder: ResourceAssetBuilder | None = None) -> None:
        self.hybrid_retriever = hybrid_retriever
        self.asset_builder = asset_builder or ResourceAssetBuilder()

    def retrieve(
        self,
        *,
        query: str,
        context: NamingSqlSelectionContext,
        loaded_resource: LoadedResource,
        target_bo_name: str | None = None,
        top_k: int = 5,
    ) -> NamingSqlRetrievalResult:
        assets = self._assets(loaded_resource, target_bo_name)
        if not assets:
            raise ContextBuildError(NO_NAMING_SQL_CANDIDATES, "no canonical NamingSQL candidates")

        by_id = {asset.asset_id: asset for asset in assets}
        recalled = []
        if self.hybrid_retriever is not None:
            returned = self.hybrid_retriever.retrieve(query, assets, semantic_limit=max(top_k, 10))
            recalled = self._canonical(returned, by_id)

        signal_text = " ".join([
            query,
            *context.query_terms,
            *(str(item.get("summary") or "") for item in context.authoritative_facts),
            *(str(item.get("summary") or "") for item in context.normative_rules),
            *(str(item.get("summary") or "") for item in context.reference_examples),
        ])
        terms = self._terms(signal_text)
        scored = sorted(
            assets,
            key=lambda asset: (
                -self._score(asset, query, terms),
                list(by_id).index(asset.asset_id),
                asset.asset_id,
            ),
        )
        ordered = []
        seen = set()
        for asset in [*recalled, *scored]:
            if asset.asset_id not in seen:
                seen.add(asset.asset_id)
                ordered.append(by_id[asset.asset_id])
        selected = ordered[:top_k]
        candidates = []
        evidence = []
        for rank, asset in enumerate(selected, start=1):
            candidate = self.asset_builder._candidate(asset).model_copy(update={"rank": rank}, deep=True)
            candidates.append(candidate)
            evidence.append(ContextEvidenceItem(
                source="resource_registry", action="candidate_recalled",
                asset_id=asset.asset_id, evidence="canonical deterministic recall",
            ))
        return NamingSqlRetrievalResult(candidates=candidates, assets=selected, evidence=evidence)

    def _assets(self, loaded_resource: LoadedResource, target_bo_name: str | None) -> list[ContextAsset]:
        assets = []
        for bo_name, bo in loaded_resource.bo_registry.items():
            if target_bo_name and bo_name != target_bo_name:
                continue
            assets.extend(self.asset_builder.naming_sql(bo_name, sql, bo) for sql in bo.naming_sql_list)
        return assets

    @staticmethod
    def _canonical(returned: Any, by_id: dict[str, ContextAsset]) -> list[ContextAsset]:
        if not isinstance(returned, (list, tuple)):
            raise ContextBuildError(INVALID_LLM_OUTPUT, "hybrid retriever returned malformed assets")
        result = []
        seen = set()
        for asset in returned:
            if not isinstance(asset, ContextAsset) or asset.asset_id not in by_id or asset.asset_id in seen:
                raise ContextBuildError(INVALID_LLM_OUTPUT, "hybrid retriever returned noncanonical assets")
            seen.add(asset.asset_id)
            result.append(by_id[asset.asset_id])
        return result

    @classmethod
    def _score(cls, asset: ContextAsset, query: str, terms: set[str]) -> int:
        content = asset.content
        exact_values = {
            str(content.get("naming_sql_id") or "").lower(),
            str(content.get("sql_name") or "").lower(),
            asset.asset_id.lower(),
        }
        exact = 10000 if query.strip().lower() in exact_values else 0
        return exact + len(cls._terms(asset.index_text) & terms)

    @staticmethod
    def _terms(value: str) -> set[str]:
        return set(re.findall(r"[\w]+", value.lower(), flags=re.UNICODE))
