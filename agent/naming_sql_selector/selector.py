from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.context_manager.errors import ContextBuildError
from agent.context_manager.models import BuildContextRequest

from .models import NamingSqlSelectRequest, NamingSqlSelectResponse


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
            return NamingSqlSelectResponse(success=False, failure_reason=error.code)

        return NamingSqlSelectResponse(
            success=True,
            candidates=deepcopy(context.resource_candidates.candidates),
            hints=deepcopy(context.requirement_hints),
            constraints=deepcopy(context.constraints),
            evidence_trace=deepcopy(context.evidence_trace),
            prompt_view=deepcopy(context.prompt_view) if request.debug else None,
        )
