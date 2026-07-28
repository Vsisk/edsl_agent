from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.llm.generate_by_llm import generate_by_llm
from agent.resource_manager.loader.registry_models import ReturnType

from .models import (
    CoverageDecision,
    CoverageKind,
    GoalRole,
    ResourceCandidate,
    ResourceTier,
    ValueGoal,
)


class KeywordDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class _GoalSemanticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_name: str
    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    target_bo_name: str | None = None
    target_field_name: str | None = None


class _KeywordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class SpecSemanticGateway:
    def __init__(
        self,
        *,
        decision_fn: Callable[..., Any] = generate_by_llm,
    ) -> None:
        self.decision_fn = decision_fn
        self.request_json = "{}"
        self.context_pack_json = "{}"

    def configure_background(
        self,
        *,
        request: Any,
        context_pack: Any,
    ) -> None:
        self.request_json = _dump(_model_dump(request))
        self.context_pack_json = _dump(_model_dump(context_pack))

    def _background(self) -> dict[str, str]:
        return {
            "request_json": self.request_json,
            "context_pack_json": self.context_pack_json,
        }

    def generate_goal(
        self,
        *,
        goal_id: str,
        node_info: Any,
        query: str,
        expected_type: ReturnType,
        role: GoalRole,
    ) -> ValueGoal:
        raw = self.decision_fn(
            prompt_template="spec_orchestrator_goal",
            llm_name="base",
            lang="zh",
            node_info_json=_dump(node_info),
            user_requirement=str(query or "")[:4000],
            **self._background(),
        )
        response = _GoalSemanticResponse.model_validate(raw)
        return ValueGoal(
            goal_id=goal_id,
            semantic_name=response.semantic_name.strip(),
            role=role,
            expected_type=expected_type.model_copy(deep=True),
            target_bo_name=response.target_bo_name,
            target_field_name=response.target_field_name,
        )

    def generate_keywords(
        self,
        *,
        goal: ValueGoal,
        query: str,
    ) -> KeywordDecision:
        raw = self.decision_fn(
            prompt_template="spec_orchestrator_keywords",
            llm_name="base",
            lang="zh",
            goal_json=_dump(goal.model_dump(mode="json")),
            user_requirement=str(query or "")[:4000],
            **self._background(),
        )
        # The tier is code-owned. Ignore any tier/tool fields returned by the model.
        allowed = {
            key: raw.get(key)
            for key in ("keywords", "aliases", "negative_keywords")
            if isinstance(raw, dict) and key in raw
        }
        try:
            response = _KeywordResponse.model_validate(allowed)
        except ValidationError:
            response = _KeywordResponse()
        return KeywordDecision(
            keywords=_bounded_strings(response.keywords),
            aliases=_bounded_strings(response.aliases),
            negative_keywords=_bounded_strings(response.negative_keywords),
        )

    def decide_coverage(
        self,
        *,
        goal: ValueGoal,
        tier: ResourceTier,
        candidates: list[ResourceCandidate],
        query: str,
    ) -> CoverageDecision:
        if not candidates:
            return _not_cover("no legal candidates")
        raw = self.decision_fn(
            prompt_template="spec_orchestrator_coverage",
            llm_name="base",
            lang="zh",
            goal_json=_dump(goal.model_dump(mode="json")),
            resource_tier=tier.value,
            candidates_json=_dump([_candidate_summary(item) for item in candidates]),
            user_requirement=str(query or "")[:4000],
            **self._background(),
        )
        try:
            decision = CoverageDecision.model_validate(raw)
            allowed_ids = {item.candidate_id for item in candidates}
            if (
                decision.selected_candidate_id is not None
                and decision.selected_candidate_id not in allowed_ids
            ):
                return _not_cover("coverage referenced an unknown candidate")
            return decision
        except (ValidationError, TypeError, ValueError):
            return _not_cover("invalid coverage decision")


def _candidate_summary(candidate: ResourceCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "kind": candidate.kind,
        "bo_name": candidate.bo_name,
        "field_name": candidate.field_name,
        "return_type": candidate.return_type.model_dump(mode="json"),
        "required_inputs": [
            item.model_dump(mode="json") for item in candidate.required_inputs
        ],
        "evidence": candidate.evidence[:10],
    }


def _not_cover(reason: str) -> CoverageDecision:
    return CoverageDecision(
        kind=CoverageKind.NOT_COVER,
        continue_search=True,
        reason=reason,
    )


def _bounded_strings(values: list[str]) -> list[str]:
    result = []
    for value in values[:20]:
        normalized = str(value or "").strip()[:256]
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))[:12000]


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value
