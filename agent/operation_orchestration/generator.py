from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from agent.operation_orchestration.models import (
    GenerateOperationsRequest,
    GenerateOperationsResponse,
    Operation,
    validate_and_sort_operations,
)
from agent.operation_orchestration.node_index import build_node_index


LLMGateway = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
_CONTAINER_CAPABILITY = "需要包含子节点"
_CONTAINER_CAPABILITY_VARIANT = re.compile(
    r"(?:不\s*需要|无需|需要)\s*包含\s*子节点"
)
_PUNCTUATION_RUN = re.compile(r"([，,；;。.!！？?])(?:\s*[，,；;。.!！？?])+")
_DANGLING_CONNECTOR = re.compile(
    r"(?:[，,；;]\s*)?(?:但是|但|并且|而且|同时|且|并)\s*$"
)


class OperationGenerator:
    """Generate and validate node-level operations from an LLM response."""

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._llm_gateway = llm_gateway or self._default_llm_gateway

    def generate(
        self, request: GenerateOperationsRequest
    ) -> GenerateOperationsResponse:
        try:
            node_index = build_node_index(request.target_tree)
        except ValueError as exc:
            raise ValueError(f"failed to summarize target tree: {exc}") from exc

        summary = [
            candidate.model_dump(mode="json") for candidate in node_index.values()
        ]
        try:
            payload = self._llm_gateway(request.query, summary)
        except Exception as exc:
            raise ValueError(f"operation generation gateway failed: {exc}") from exc

        try:
            generated = GenerateOperationsResponse.model_validate(payload, strict=True)
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid operation generation payload: {exc}") from exc

        if not generated.operations:
            raise ValueError("operation generation requires at least one operation")

        original_ids = [operation.op_id for operation in generated.operations]
        duplicate_ids = {
            op_id for op_id in original_ids if original_ids.count(op_id) > 1
        }
        if duplicate_ids:
            duplicates = ", ".join(sorted(duplicate_ids))
            raise ValueError(f"duplicate original operation id: {duplicates}")

        id_mapping = {
            original_id: f"op_{index}"
            for index, original_id in enumerate(original_ids)
        }
        operations = [
            self._normalize_operation(operation, id_mapping)
            for operation in generated.operations
        ]

        try:
            validate_and_sort_operations(operations)
        except ValueError as exc:
            raise ValueError(f"invalid operation dependency graph: {exc}") from exc

        self._enrich_container_queries(operations)
        return GenerateOperationsResponse(operations=operations)

    @staticmethod
    def _normalize_operation(
        operation: Operation, id_mapping: dict[str, str]
    ) -> Operation:
        return operation.model_copy(
            update={
                "op_id": id_mapping[operation.op_id],
                "depends_on": [
                    id_mapping.get(dependency, dependency)
                    for dependency in operation.depends_on
                ],
                "target_from": (
                    id_mapping.get(operation.target_from, operation.target_from)
                    if operation.target_from is not None
                    else None
                ),
                "target_jsonpath": None,
                "target_node_id": None,
                "output_node_id": None,
                "status": "pending",
                "error_message": None,
            }
        )

    @staticmethod
    def _enrich_container_queries(operations: list[Operation]) -> None:
        operation_by_id = {operation.op_id: operation for operation in operations}
        container_ids: set[str] = set()

        for downstream in operations:
            if downstream.intent_type != "create_node" or not downstream.depends_on:
                continue
            target_source = (
                downstream.depends_on[0]
                if len(downstream.depends_on) == 1
                else downstream.target_from
            )
            if target_source is None:
                continue
            upstream = operation_by_id[target_source]
            if upstream.intent_type == "create_node":
                container_ids.add(target_source)

        for operation in operations:
            if operation.op_id in container_ids:
                operation.query = OperationGenerator._normalize_container_query(
                    operation.query
                )

    @staticmethod
    def _normalize_container_query(query: str) -> str:
        cleaned = _CONTAINER_CAPABILITY_VARIANT.sub("", query).strip()
        cleaned = _PUNCTUATION_RUN.sub(r"\1", cleaned)
        cleaned = cleaned.rstrip(" \t\r\n，,；;。.!！？?")
        cleaned = _DANGLING_CONNECTOR.sub("", cleaned)
        cleaned = cleaned.rstrip(" \t\r\n，,；;。.!！？?")
        if not cleaned:
            return f"{_CONTAINER_CAPABILITY}。"
        return f"{cleaned}；{_CONTAINER_CAPABILITY}。"

    @staticmethod
    def _default_llm_gateway(
        query: str, target_tree_summary: list[dict[str, Any]]
    ) -> dict[str, Any]:
        from agent.llm.generate_by_llm import generate_by_llm

        return generate_by_llm(
            "operation_generator_prompt",
            query=query,
            target_tree_summary_json=json.dumps(
                target_tree_summary, ensure_ascii=False
            ),
        )
