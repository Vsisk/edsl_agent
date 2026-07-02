from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.context_manager.errors import (
    AI_CONFIGURATION_REQUIRED,
    EDSL_NODE_NOT_FOUND,
    EMBEDDING_FAILED,
    INVALID_LLM_OUTPUT,
    LLM_ORGANIZER_FAILED,
    LLM_RERANK_FAILED,
    NO_NAMING_SQL_CANDIDATES,
    RULE_FILE_MISSING,
    UNSUPPORTED_CONTEXT_CHAIN,
    ContextBuildError,
)
from agent.context_manager.models import BuildContextRequest

from .models import NamingSqlSelectRequest, NamingSqlSelectResponse


KNOWN_CONTEXT_ERROR_CODES = frozenset({
    AI_CONFIGURATION_REQUIRED,
    EMBEDDING_FAILED,
    LLM_RERANK_FAILED,
    LLM_ORGANIZER_FAILED,
    INVALID_LLM_OUTPUT,
    RULE_FILE_MISSING,
    EDSL_NODE_NOT_FOUND,
    UNSUPPORTED_CONTEXT_CHAIN,
    NO_NAMING_SQL_CANDIDATES,
})


class NamingSqlSelector:
    """Thin public facade over NamingSQL context construction."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def select(self, request: NamingSqlSelectRequest) -> NamingSqlSelectResponse:
        context_request = BuildContextRequest(
            site_id=request.site_id,
            project_id=request.project_id,
            query=request.query,
            node=deepcopy(request.node),
            json_path=request.json_path,
            target_bo_name=request.target_bo_name,
            parent_bo_hint=request.parent_bo_hint,
            target_logic_area_id_list=deepcopy(request.target_logic_area_id_list),
            top_k=request.top_k,
            debug=request.debug,
        )
        try:
            context = self.manager.build_context(context_request)
        except ContextBuildError as error:
            if error.code not in KNOWN_CONTEXT_ERROR_CODES:
                raise
            return NamingSqlSelectResponse(success=False, failure_reason=error.code)

        return NamingSqlSelectResponse(
            success=True,
            candidates=deepcopy(context.resource_candidates.candidates),
            context_requirements_hint=deepcopy(context.requirement_hints),
            selection_constraints=deepcopy(context.constraints),
            evidence_trace=deepcopy(context.evidence_trace),
            prompt_view=deepcopy(context.prompt_view) if request.debug else None,
        )
