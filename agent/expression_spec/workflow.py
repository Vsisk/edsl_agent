from __future__ import annotations

from typing import Any

from .expression_spec_generator import ExpressionSpecGenerator
from .models import ExpressionContextSpec, SearchRequest, SearchResult
from .resource_search_service import ResourceSearchService
from .search_request_generator import SearchRequestGenerator


class SpecGenerationError(RuntimeError):
    pass


class ExpressionSpecWorkflow:
    def __init__(
        self,
        *,
        context_manager: Any,
        search_request_generator: SearchRequestGenerator,
        resource_search_service: ResourceSearchService,
        expression_spec_generator: ExpressionSpecGenerator,
        max_rounds: int = 6,
    ) -> None:
        self.context_manager = context_manager
        self.search_request_generator = search_request_generator
        self.resource_search_service = resource_search_service
        self.expression_spec_generator = expression_spec_generator
        self.max_rounds = max_rounds

    async def generate_spec(
        self,
        *,
        query: str,
        node: Any,
        node_path: str = "",
        bill_type: str | None = None,
    ) -> ExpressionContextSpec:
        context = self.context_manager.get_context(
            query=query,
            node=node,
            node_path=node_path,
        )
        draft, search_requests = self.search_request_generator.generate_initial(
            query=query,
            node=node,
            bill_type=bill_type,
            context=context,
        )
        search_history: list[SearchResult] = []
        request_history: list[SearchRequest] = []

        for _ in range(self.max_rounds):
            if not search_requests:
                break
            request_history.extend(search_requests)
            results = await self.resource_search_service.search_batch(search_requests)
            search_history.extend(results)
            spec_result = self.expression_spec_generator.generate(
                query=query,
                node=node,
                draft=draft,
                search_requests=request_history,
                search_results=search_history,
                context=context,
            )
            if spec_result.closed and spec_result.spec is not None:
                return spec_result.spec
            search_requests = self.search_request_generator.generate_followup(
                missing_requirements=spec_result.missing_requirements,
                search_results=search_history,
                context=context,
            )

        raise SpecGenerationError("expression spec cannot be resolved")
