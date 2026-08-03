from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, StrictBool

from agent.llm.generate_by_llm import generate_by_llm


class _QuerySpecClarityResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_explicit_spec: StrictBool
    reason: str = ""


class QuerySpecClarityAnalyzer:
    def __init__(
        self,
        *,
        decision_fn: Callable[..., Any] = generate_by_llm,
    ) -> None:
        self.decision_fn = decision_fn

    def is_explicit_spec(
        self,
        *,
        query: str,
        node_info: Any = None,
        expected_type: Any = None,
        request: Any = None,
        context_pack: Any = None,
    ) -> bool:
        try:
            raw = self.decision_fn(
                prompt_template="query_spec_clarity",
                llm_name="base",
                lang="zh",
                user_requirement=str(query or "")[:4000],
                node_info_json=_dump(node_info),
                expected_type_json=_dump(expected_type),
                request_json=_dump(request),
                context_pack_json=_dump(context_pack),
            )
            return _QuerySpecClarityResponse.model_validate(raw).is_explicit_spec
        except Exception:
            return False


def _dump(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )[:12000]
