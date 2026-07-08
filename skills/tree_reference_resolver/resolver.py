from __future__ import annotations

from typing import Any

from .candidate_merger import CandidateMerger
from .candidate_retriever import CandidateRetriever
from .llm_reranker import LLMReranker
from .models import TreeReferenceResolveInput, TreeReferenceResolveOutput
from .node_index_builder import NodeIndexBuilder
from .reference_validator import ReferenceValidator
from .search_spec_builder import SearchSpecBuilder


def _dump(value: Any) -> Any:
    if isinstance(value, list):
        return [_dump(item) for item in value]
    return value.model_dump() if hasattr(value, "model_dump") else value


class TreeReferenceResolver:
    def __init__(
        self,
        node_index_builder: NodeIndexBuilder | None = None,
        search_spec_builder: SearchSpecBuilder | None = None,
        candidate_retriever: CandidateRetriever | None = None,
        candidate_merger: CandidateMerger | None = None,
        llm_reranker: LLMReranker | None = None,
        reference_validator: ReferenceValidator | None = None,
    ):
        self.node_index_builder = node_index_builder or NodeIndexBuilder()
        self.search_spec_builder = search_spec_builder or SearchSpecBuilder()
        self.candidate_retriever = candidate_retriever or CandidateRetriever()
        self.candidate_merger = candidate_merger or CandidateMerger()
        self.llm_reranker = llm_reranker or LLMReranker()
        self.reference_validator = reference_validator or ReferenceValidator()

    def resolve(self, request: TreeReferenceResolveInput) -> TreeReferenceResolveOutput:
        if not isinstance(request.tree_json, dict) or not request.tree_json:
            return TreeReferenceResolveOutput(success=False, failure_reason="INVALID_TREE_JSON")
        if not isinstance(request.target_node, dict) or not request.target_node:
            return TreeReferenceResolveOutput(success=False, failure_reason="INVALID_TARGET_NODE")
        try:
            node_index = self.node_index_builder.build(request.tree_json)
            spec = self.search_spec_builder.build(request, node_index)
            raw = self.candidate_retriever.retrieve(request, spec, node_index)
            merged = self.candidate_merger.merge(raw, request)
        except (KeyError, TypeError, ValueError):
            return TreeReferenceResolveOutput(success=False, failure_reason="INVALID_TREE_JSON")
        debug = None
        if request.debug:
            debug = {"node_index_count": len(node_index), "search_spec": _dump(spec), "raw_candidates": _dump(raw), "merged_candidates": _dump(merged), "validation_errors": {}}
        if not merged:
            return TreeReferenceResolveOutput(success=False, failure_reason="NO_CANDIDATE", debug_info=debug)
        ranked = self.llm_reranker.rerank(request, spec, merged)
        validation_errors: dict[str, list[str]] = {}
        selected = None
        for candidate in ranked:
            valid, errors = self.reference_validator.validate(candidate, request, spec, node_index)
            if valid:
                selected = candidate
                break
            validation_errors[f"{candidate.node_id}|{candidate.json_path}"] = errors
        if debug is not None:
            debug["validation_errors"] = validation_errors
            if self.llm_reranker.last_error:
                debug["llm_rerank_error"] = self.llm_reranker.last_error
        if selected is None:
            return TreeReferenceResolveOutput(success=False, candidates=ranked, failure_reason="NO_VALID_REFERENCE_NODE", debug_info=debug)
        if not selected.evidence:
            selected.evidence = ["selected as the highest-ranked valid local candidate"]
        if not selected.match_reason:
            selected.match_reason = selected.evidence[0]
        return TreeReferenceResolveOutput(success=True, selected=selected, candidates=ranked, debug_info=debug)
