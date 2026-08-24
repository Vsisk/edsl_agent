from __future__ import annotations

import re
from typing import Any, Callable

from .models import MissingRequirement, SearchRequest, SearchResult, SpecDraft


InitialBuilder = Callable[..., tuple[SpecDraft, list[SearchRequest]]]


class SearchRequestGenerator:
    def __init__(self, initial_builder: InitialBuilder | None = None) -> None:
        self.initial_builder = initial_builder

    def generate_initial(
        self,
        *,
        query: str,
        node: Any,
        bill_type: str | None,
        context: Any,
    ) -> tuple[SpecDraft, list[SearchRequest]]:
        if self.initial_builder is None:
            raise NotImplementedError(
                "SearchRequestGenerator requires an initial_builder for now"
            )
        draft, requests = self.initial_builder(
            query=query,
            node=node,
            bill_type=bill_type,
            context=context,
        )
        return draft, requests

    def generate_followup(
        self,
        *,
        missing_requirements: list[MissingRequirement],
        search_results: list[SearchResult],
        context: Any,
    ) -> list[SearchRequest]:
        del search_results, context
        requests = []
        seen = set()
        for index, missing in enumerate(missing_requirements):
            key = (
                missing.requirement_id,
                missing.semantic,
                tuple(missing.resource_types),
                missing.expected_return_type,
                missing.scope,
            )
            if key in seen:
                continue
            seen.add(key)
            introduced = missing.introduced_by or {}
            param = str(introduced.get("param") or "").strip()
            keywords = _keywords(missing.semantic, param)
            requests.append(
                SearchRequest(
                    request_id=f"followup_{index}_{_slug(missing.semantic or param)}",
                    requirement_id=missing.requirement_id,
                    resource_types=missing.resource_types,
                    keywords=keywords,
                    semantic=missing.semantic,
                    scope=missing.scope,
                    expected_return_type=missing.expected_return_type,
                    expected_cardinality=missing.expected_cardinality,
                    constraints=missing.constraints,
                    introduced_by=missing.introduced_by,
                )
            )
        return requests


def _keywords(semantic: str, param: str) -> list[str]:
    values = []
    for value in [semantic, param]:
        values.extend(re.findall(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]+", value or ""))
    result = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result or [semantic]


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip()).strip("_")
    return slug[:40] or "missing"
