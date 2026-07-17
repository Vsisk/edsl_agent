from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from agent.operation_orchestration.models import (
    OperationToolLoopRequest,
    OperationToolLoopResponse,
    ToolDecision,
)
from agent.operation_orchestration.runtime import OperationToolRuntime


LLMGateway = Callable[..., dict[str, Any]]
MAX_TREE_SUMMARY_ITEMS = 200
MAX_HISTORY_ITEMS = 20
MAX_SUMMARY_TEXT = 256


class OperationToolLoop:
    """Run one LLM-selected, registry-dispatched mapping-content tool per round."""

    def __init__(
        self,
        *,
        llm_gateway: LLMGateway | None = None,
        action_adapter: Any | None = None,
        runtime_factory: Callable[..., OperationToolRuntime] = OperationToolRuntime,
    ) -> None:
        self._llm_gateway = llm_gateway or self._default_llm_gateway
        self._action_adapter = action_adapter
        self._runtime_factory = runtime_factory

    def run(self, request: OperationToolLoopRequest) -> OperationToolLoopResponse:
        try:
            runtime = self._runtime_factory(
                request.target_tree,
                action_adapter=self._action_adapter,
                site_id=request.site_id,
                project_id=request.project_id,
            )
        except Exception:
            return OperationToolLoopResponse(
                success=False,
                target_tree=deepcopy(request.target_tree),
                operations=[],
                error_message="operation tool runtime initialization failed",
            )

        catalog = runtime.registry.tool_catalog()
        for _ in range(request.max_steps):
            try:
                payload = self._llm_gateway(
                    query=request.query,
                    tree_summary=self._tree_summary(runtime),
                    tool_catalog=deepcopy(catalog),
                    tool_history=self._tool_history(runtime),
                )
                decision = ToolDecision.model_validate(payload, strict=True)
            except Exception:
                return self._response(
                    runtime,
                    success=False,
                    error_message="operation tool decision failed",
                )

            try:
                runtime.execute(decision.tool_name, decision.arguments)
            except Exception:
                return self._response(
                    runtime,
                    success=False,
                    error_message=f"operation tool {decision.tool_name} failed",
                )
            if runtime.finished:
                return self._response(runtime, success=True)

        return self._response(
            runtime,
            success=False,
            error_message=(
                f"operation tool loop exceeded max_steps={request.max_steps}"
            ),
        )

    @staticmethod
    def _response(
        runtime: OperationToolRuntime,
        *,
        success: bool,
        error_message: str | None = None,
    ) -> OperationToolLoopResponse:
        return OperationToolLoopResponse(
            success=success,
            target_tree=runtime.tree,
            operations=[operation.model_copy(deep=True) for operation in runtime.operations],
            tool_calls=[trace.model_copy(deep=True) for trace in runtime.traces],
            tree_version=runtime.version,
            error_message=error_message,
        )

    @staticmethod
    def _tree_summary(runtime: OperationToolRuntime) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for candidate in list(runtime.index.values())[:MAX_TREE_SUMMARY_ITEMS]:
            item = candidate.model_dump(mode="json")
            for key in (
                "xml_name",
                "annotation",
                "parent_xml_name",
                "tree_node_type",
            ):
                value = item.get(key)
                if isinstance(value, str):
                    item[key] = value[:MAX_SUMMARY_TEXT]
            summary.append(item)
        return summary

    @staticmethod
    def _tool_history(runtime: OperationToolRuntime) -> list[dict[str, Any]]:
        return [
            trace.model_dump(mode="json")
            for trace in runtime.traces[-MAX_HISTORY_ITEMS:]
        ]

    @staticmethod
    def _default_llm_gateway(
        *,
        query: str,
        tree_summary: list[dict[str, Any]],
        tool_catalog: list[dict[str, Any]],
        tool_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from agent.llm.generate_by_llm import generate_by_llm

        return generate_by_llm(
            "operation_tool_loop_prompt",
            query=query,
            tree_summary_json=json.dumps(tree_summary, ensure_ascii=False),
            tool_catalog_json=json.dumps(tool_catalog, ensure_ascii=False),
            tool_history_json=json.dumps(tool_history, ensure_ascii=False),
        )
