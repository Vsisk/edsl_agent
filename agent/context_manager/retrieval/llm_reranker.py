from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from agent.context_manager.errors import INVALID_LLM_OUTPUT, LLM_RERANK_FAILED, ContextBuildError
from agent.context_manager.models import ContextAsset, ContextEvidenceItem, ContextRequirementHint
from agent.llm.llm_client import LLMClient
from agent.llm.prompt_manager import PromptManager, prompt_manager

MAX_ASSET_CANDIDATES = 40
MAX_QUERY_CHARS = 4_000
MAX_CONTEXT_CHARS = 8_000
MAX_ASSET_SUMMARY_CHARS = 1_000
MAX_ASSET_ID_CHARS = 256
MAX_ASSET_TYPE_CHARS = 64


class JsonClient(Protocol):
    def complete_json(self, prompt: str) -> dict[str, Any]: ...


class LLMRerankOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_asset_ids: list[str]
    rejected_assets: list[dict[str, Any]]
    context_requirement_hints: list[ContextRequirementHint]
    evidence_trace: list[ContextEvidenceItem]


@dataclass(frozen=True)
class LLMRerankResult:
    selected_assets: list[ContextAsset]
    rejected_assets: list[dict[str, Any]]
    context_requirement_hints: list[ContextRequirementHint]
    evidence_trace: list[ContextEvidenceItem]


class LLMReranker:
    def __init__(self, client: JsonClient | None = None, prompt_manager: PromptManager | None = None) -> None:
        self.client = client or LLMClient()
        self.prompt_manager = prompt_manager or globals()["prompt_manager"]

    def rerank(self, query: str, assets: list[ContextAsset], context: Any) -> LLMRerankResult:
        bounded_assets = assets[:MAX_ASSET_CANDIDATES]
        candidates = [
            {"asset_id": item.asset_id[:MAX_ASSET_ID_CHARS], "asset_type": item.asset_type[:MAX_ASSET_TYPE_CHARS], "semantic_summary": item.index_text[:MAX_ASSET_SUMMARY_CHARS]}
            for item in bounded_assets
        ]
        prompt = self.prompt_manager.render(
            "context_namingsql_reranker", lang="zh",
            query=str(query)[:MAX_QUERY_CHARS],
            context_json=self._bounded_json(context, MAX_CONTEXT_CHARS),
            candidates_json=json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
        )
        try:
            raw = self.client.complete_json(prompt)
        except Exception as exc:
            raise ContextBuildError(LLM_RERANK_FAILED, "LLM reranking request failed") from exc
        try:
            output = LLMRerankOutput.model_validate(raw)
            ids = output.selected_asset_ids
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate selected asset id")
            asset_by_id = {item.asset_id[:MAX_ASSET_ID_CHARS]: item for item in bounded_assets}
            if len(asset_by_id) != len(bounded_assets) or any(item not in asset_by_id for item in ids):
                raise ValueError("unknown or ambiguous selected asset id")
            self._validate_references(output, set(asset_by_id))
        except (ValidationError, ValueError, TypeError) as exc:
            raise ContextBuildError(INVALID_LLM_OUTPUT, "LLM reranking output violates contract") from exc
        return LLMRerankResult(
            selected_assets=[asset_by_id[item] for item in ids],
            rejected_assets=output.rejected_assets,
            context_requirement_hints=output.context_requirement_hints,
            evidence_trace=output.evidence_trace,
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
        referenced = [item.get("asset_id") for item in output.rejected_assets if item.get("asset_id") is not None]
        referenced += [item.asset_id for item in output.evidence_trace if item.asset_id is not None]
        referenced += [asset_id for hint in output.context_requirement_hints for asset_id in hint.bind_to_candidates]
        if any(asset_id not in allowed for asset_id in referenced):
            raise ValueError("output references unknown asset id")
