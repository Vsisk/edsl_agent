from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.context_manager.errors import (
    AI_CONFIGURATION_REQUIRED,
    EMBEDDING_FAILED,
    INVALID_LLM_OUTPUT,
    LLM_ORGANIZER_FAILED,
    LLM_RERANK_FAILED,
    NO_NAMING_SQL_CANDIDATES,
    ContextBuildError,
)

from .context_adapter import CONTEXT_PACK_FAILED, NamingSqlContextAdapter
from .models import NamingSqlSelectRequest, NamingSqlSelectResponse, SelectionMode
from .retrieval import NamingSqlCandidateRetriever


AI_FALLBACK_CODES = frozenset({
    AI_CONFIGURATION_REQUIRED,
    EMBEDDING_FAILED,
    LLM_RERANK_FAILED,
    LLM_ORGANIZER_FAILED,
    INVALID_LLM_OUTPUT,
})
KNOWN_CONTEXT_ERROR_CODES = frozenset({*AI_FALLBACK_CODES, CONTEXT_PACK_FAILED, NO_NAMING_SQL_CANDIDATES})


class NamingSqlSelector:
    """Select canonical NamingSQL after ContextPack recall has completed."""

    def __init__(
        self,
        loaded_resource: Any,
        *,
        context_adapter: Any = None,
        candidate_retriever: Any = None,
        reranker: Any = None,
    ) -> None:
        self.loaded_resource = loaded_resource
        self.context_adapter = context_adapter or NamingSqlContextAdapter()
        self.candidate_retriever = candidate_retriever or NamingSqlCandidateRetriever()
        self.reranker = reranker

    def select(self, request: NamingSqlSelectRequest) -> NamingSqlSelectResponse:
        try:
            selection_context = self.context_adapter.adapt(request.context_pack)
            retrieval = self.candidate_retriever.retrieve(
                query=request.query,
                context=selection_context,
                loaded_resource=self.loaded_resource,
                target_bo_name=request.target_bo_name,
                top_k=request.top_k,
            )
        except ContextBuildError as error:
            if error.code not in KNOWN_CONTEXT_ERROR_CODES:
                raise
            return NamingSqlSelectResponse(success=False, failure_reason=error.code)

        warnings = list(selection_context.warnings)
        candidates = deepcopy(retrieval.candidates)
        evidence = deepcopy(retrieval.evidence)
        mode = SelectionMode.DETERMINISTIC_FALLBACK

        if self.reranker is not None:
            try:
                result = self.reranker.rerank(
                    request.query,
                    retrieval.assets,
                    selection_context.model_dump(mode="json"),
                )
                selected_assets = self._canonical_selected(
                    getattr(result, "selected_assets", None), retrieval.assets, request.top_k
                )
                candidate_by_id = {item.candidate_id: item for item in retrieval.candidates}
                candidates = [
                    candidate_by_id[asset.asset_id].model_copy(update={"rank": rank}, deep=True)
                    for rank, asset in enumerate(selected_assets, start=1)
                ]
                evidence.extend(deepcopy(list(getattr(result, "evidence_trace", []) or [])))
                mode = SelectionMode.LLM
            except ContextBuildError as error:
                if error.code not in AI_FALLBACK_CODES:
                    raise
                warnings.append(error.code)

        return NamingSqlSelectResponse(
            success=True,
            selection_mode=mode,
            warnings=list(dict.fromkeys(warnings)),
            candidates=candidates,
            evidence_trace=evidence,
            prompt_view=(
                {"selection_context": selection_context.model_dump(mode="json")}
                if request.debug else None
            ),
        )

    @staticmethod
    def _canonical_selected(returned: Any, originals: list[Any], top_k: int) -> list[Any]:
        if not isinstance(returned, (list, tuple)) or not returned or len(returned) > top_k:
            raise ContextBuildError(INVALID_LLM_OUTPUT, "invalid selected assets")
        by_id = {item.asset_id: item for item in originals}
        result = []
        seen = set()
        for item in returned:
            asset_id = getattr(item, "asset_id", None)
            if asset_id not in by_id or asset_id in seen:
                raise ContextBuildError(INVALID_LLM_OUTPUT, "noncanonical selected assets")
            seen.add(asset_id)
            result.append(by_id[asset_id])
        return result
