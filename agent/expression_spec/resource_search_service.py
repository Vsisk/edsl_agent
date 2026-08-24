from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from .models import SearchRequest, SearchResult


Searcher = Callable[[SearchRequest], Any]


class ResourceSearchService:
    def __init__(self, *, searchers: dict[str, Searcher] | None = None) -> None:
        self.searchers = searchers or {}

    async def search(self, request: SearchRequest) -> SearchResult:
        candidates = []
        for resource_type in request.resource_types:
            searcher = self.searchers.get(resource_type)
            if searcher is None:
                continue
            try:
                raw = searcher(request)
                value = await raw if inspect.isawaitable(raw) else raw
            except Exception as exc:
                candidates.append(
                    {
                        "resource_type": resource_type,
                        "error": str(exc),
                    }
                )
                continue
            selected, extra_candidates = _normalize_searcher_value(value)
            candidates.extend(extra_candidates)
            if selected is not None:
                return SearchResult(
                    request_id=request.request_id,
                    success=True,
                    selected_resource=selected,
                    candidates=candidates,
                )
        return SearchResult(
            request_id=request.request_id,
            success=False,
            selected_resource=None,
            candidates=candidates,
        )

    async def search_batch(self, requests: list[SearchRequest]) -> list[SearchResult]:
        return list(await asyncio.gather(*(self.search(request) for request in requests)))


def _normalize_searcher_value(value: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if isinstance(value, SearchResult):
        return value.selected_resource, value.candidates
    if value is None:
        return None, []
    if isinstance(value, dict):
        return value, [value]
    if isinstance(value, list):
        candidates = [item for item in value if isinstance(item, dict)]
        selected = candidates[0] if candidates else None
        return selected, candidates
    return {"value": value}, [{"value": value}]
