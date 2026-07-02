from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.context_manager.errors import INVALID_LLM_OUTPUT, LLM_RERANK_FAILED, ContextBuildError
from agent.context_manager.models import ContextAsset, ContextEvidenceItem, ContextRequirementHint
from agent.llm.llm_client import LLMClient
from agent.llm.prompt_manager import PromptManager, prompt_manager

MAX_ASSET_CANDIDATES = 40
MAX_QUERY_CHARS = 4_000
MAX_CONTEXT_CHARS = 8_000
MAX_ASSET_SUMMARY_CHARS = 1_000
MAX_ASSET_TYPE_CHARS = 64


class JsonClient(Protocol):
    def complete_json(self, prompt: str) -> dict[str, Any]: ...


class LLMRerankOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    selected_asset_ids: list[str]
    rejected_assets: list["LLMRejectedAsset"] = Field(default_factory=list)
    context_requirement_hints: list[ContextRequirementHint] = Field(default_factory=list)
    evidence_trace: list[ContextEvidenceItem] = Field(default_factory=list)


class LLMRejectedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    asset_id: str
    reason: str


@dataclass(frozen=True)
class LLMRerankResult:
    selected_asset_ids: list[str]
    selected_assets: list[ContextAsset]
    rejected_assets: list[LLMRejectedAsset]
    context_requirement_hints: list[ContextRequirementHint]
    evidence_trace: list[ContextEvidenceItem]


class LLMReranker:
    def __init__(self, client: JsonClient | None = None, prompt_manager: PromptManager | None = None) -> None:
        self.client = client or LLMClient()
        self.prompt_manager = prompt_manager or globals()["prompt_manager"]

    def rerank(self, query: str, assets: list[ContextAsset], context: Any) -> LLMRerankResult:
        try:
            bounded_assets = assets[:MAX_ASSET_CANDIDATES]
            alias_to_asset = {
                f"c{index:04d}": item for index, item in enumerate(bounded_assets)
            }
            candidates = [
                {
                    "asset_id": alias,
                    "asset_type": item.asset_type[:MAX_ASSET_TYPE_CHARS],
                    "semantic_summary": item.index_text[:MAX_ASSET_SUMMARY_CHARS],
                }
                for alias, item in alias_to_asset.items()
            ]
            prompt = self.prompt_manager.render(
                "context_namingsql_reranker", lang="zh",
                query=str(query)[:MAX_QUERY_CHARS],
                context_json=self._bounded_json(context, MAX_CONTEXT_CHARS),
                candidates_json=json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
            )
        except Exception as exc:
            raise ContextBuildError(
                LLM_RERANK_FAILED, "LLM reranking prompt preparation failed"
            ) from exc
        try:
            raw = self.client.complete_json(prompt)
        except Exception as exc:
            raise ContextBuildError(LLM_RERANK_FAILED, "LLM reranking request failed") from exc
        try:
            output = LLMRerankOutput.model_validate(raw)
            ids = output.selected_asset_ids
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate selected asset id")
            self._validate_references(output, set(alias_to_asset))
            rejected_ids = {item.asset_id for item in output.rejected_assets}
            if set(ids) & rejected_ids:
                raise ValueError("selected and rejected asset ids overlap")
            selected_assets = [alias_to_asset[item] for item in ids]
            rejected_assets = [
                item.model_copy(update={"asset_id": alias_to_asset[item.asset_id].asset_id})
                for item in output.rejected_assets
            ]
            evidence_trace = [
                item.model_copy(
                    update={"asset_id": alias_to_asset[item.asset_id].asset_id}
                )
                if item.asset_id is not None
                else item
                for item in output.evidence_trace
            ]
            requirement_hints = [
                item.model_copy(
                    update={
                        "bind_to_candidates": [
                            alias_to_asset[alias].asset_id
                            for alias in item.bind_to_candidates
                        ]
                    }
                )
                for item in output.context_requirement_hints
            ]
            canonical_selected_ids = [item.asset_id for item in selected_assets]
            if set(canonical_selected_ids) & {item.asset_id for item in rejected_assets}:
                raise ValueError("selected and rejected canonical asset ids overlap")
        except (ValidationError, ValueError, TypeError) as exc:
            raise ContextBuildError(INVALID_LLM_OUTPUT, "LLM reranking output violates contract") from exc
        return LLMRerankResult(
            selected_asset_ids=canonical_selected_ids,
            selected_assets=selected_assets,
            rejected_assets=rejected_assets,
            context_requirement_hints=requirement_hints,
            evidence_trace=evidence_trace,
        )

    @staticmethod
    def _bounded_json(value: Any, limit: int) -> str:
        try:
            serialized = json.dumps(LLMReranker._without_sql(value), ensure_ascii=False, default=str, separators=(",", ":"))
        except Exception:
            serialized = "{}"
        return serialized[:limit]

    @staticmethod
    def _without_sql(value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if isinstance(value, dict):
            return {
                key: LLMReranker._without_sql(item)
                for key, item in value.items()
                if str(key).lower() != "sql_command"
            }
        if isinstance(value, (list, tuple)):
            return [LLMReranker._without_sql(item) for item in value]
        return value

    @staticmethod
    def _validate_references(output: LLMRerankOutput, allowed: set[str]) -> None:
        referenced = list(output.selected_asset_ids)
        referenced += [item.asset_id for item in output.rejected_assets]
        referenced += [item.asset_id for item in output.evidence_trace if item.asset_id is not None]
        referenced += [asset_id for hint in output.context_requirement_hints for asset_id in hint.bind_to_candidates]
        if any(asset_id not in allowed for asset_id in referenced):
            raise ValueError("output references unknown asset id")
