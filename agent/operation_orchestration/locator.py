from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from agent.llm.generate_by_llm import generate_by_llm
from agent.operation_orchestration.models import (
    LocateOperationRequest,
    LocateOperationResponse,
    Operation,
)
from agent.operation_orchestration.node_index import build_node_index, is_valid_candidate


LLMGateway = Callable[[str, str, list[dict[str, Any]]], dict[str, Any]]
_NonBlankText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]


class LocationSelection(BaseModel):
    """Strict, untrusted inbound selection returned by the locator gateway."""

    model_config = ConfigDict(extra="forbid")

    selected_node_id: _NonBlankText
    selected_jsonpath: _NonBlankText
    confidence: Literal["high", "medium", "low"]
    reason: _NonBlankText


class OperationLocator:
    """Locate an independent operation using a constrained candidate gateway.

    Injected gateways receive ``(query, intent_type, candidates)`` where candidates
    is a list of JSON-compatible ``NodeLocateCandidate`` dictionaries in DFS order.
    """

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._llm_gateway = llm_gateway or self._default_llm_gateway

    def locate(self, request: LocateOperationRequest) -> LocateOperationResponse:
        operation = request.operation.model_copy(deep=True)

        if operation.depends_on:
            return self._failure(
                operation,
                [],
                "operation locator only handles operations without dependencies",
            )

        try:
            node_index = build_node_index(request.target_tree)
        except Exception as exc:
            return self._failure(
                operation, [], f"failed to build operation candidate index: {exc}"
            )

        candidates = [
            candidate.model_dump(mode="json")
            for candidate in node_index.values()
            if is_valid_candidate(operation.intent_type, candidate)
        ]
        if not candidates:
            return self._failure(
                operation,
                candidates,
                f"no valid candidates for intent {operation.intent_type}",
            )

        try:
            payload = self._llm_gateway(
                operation.query, operation.intent_type, candidates
            )
            selection = LocationSelection.model_validate(payload, strict=True)
            if selection.confidence == "low":
                raise ValueError("locator returned low confidence")

            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate["node_id"] == selection.selected_node_id
                ),
                None,
            )
            if selected is None:
                raise ValueError("selected node_id is not a supplied candidate")
            if selected["jsonpath"] != selection.selected_jsonpath:
                raise ValueError(
                    "selected jsonpath does not match the selected candidate"
                )
        except Exception as exc:
            return self._fallback_or_failure(operation, candidates, str(exc))

        return self._success(operation, candidates, selected)

    @staticmethod
    def _success(
        operation: Operation,
        candidates: list[dict[str, Any]],
        selected: dict[str, Any],
    ) -> LocateOperationResponse:
        operation.target_node_id = selected["node_id"]
        operation.target_jsonpath = selected["jsonpath"]
        operation.status = "located"
        operation.error_message = None
        return LocateOperationResponse(
            success=True, operation=operation, candidates=candidates
        )

    def _fallback_or_failure(
        self,
        operation: Operation,
        candidates: list[dict[str, Any]],
        reason: str,
    ) -> LocateOperationResponse:
        if operation.intent_type == "create_node":
            root_candidate = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate["parent_node_id"] is None
                ),
                None,
            )
            if root_candidate is not None:
                return self._success(operation, candidates, root_candidate)
            reason = f"create fallback found no valid root candidate: {reason}"
        return self._failure(
            operation, candidates, f"operation location failed: {reason}"
        )

    @staticmethod
    def _failure(
        operation: Operation,
        candidates: list[dict[str, Any]],
        message: str,
    ) -> LocateOperationResponse:
        operation.status = "failed"
        operation.error_message = message
        return LocateOperationResponse(
            success=False,
            operation=operation,
            candidates=candidates,
            error_message=message,
        )

    @staticmethod
    def _default_llm_gateway(
        query: str, intent_type: str, candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return generate_by_llm(
            "operation_locator_prompt",
            query=query,
            intent_type=intent_type,
            candidates_json=json.dumps(candidates, ensure_ascii=False),
        )
