from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from itertools import islice
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from agent.operation_orchestration.models import (
    GenerateOperationsRequest,
    GenerateOperationsResponse,
    Operation,
    validate_and_sort_operations,
)
from agent.operation_orchestration.node_index import (
    NodeLocateCandidate,
    build_node_index,
)


LLMGateway = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
MAX_TREE_SUMMARY_CANDIDATES = 200
MAX_SUMMARY_TEXT_LENGTH = 256
MAX_SUMMARY_PATH_LENGTH = 512
MAX_GENERATOR_QUERY_BYTES = 4096
MAX_GENERATOR_PROMPT_BYTES = 32000
GENERATOR_PROMPT_TEMPLATE_OVERHEAD_BYTES = 4096
GENERATOR_PROMPT_INPUT_OVERHEAD_BYTES = len(
    "query:\ntarget_tree_summary_json:\n".encode("utf-8")
)
_CONTAINER_CAPABILITY = "需要包含子节点"
_CONTAINER_CAPABILITY_VARIANT = re.compile(
    r"(?:(?:不\s*(?:需要|应该|需|必)|无\s*(?:需|须)|需要)\s*包含\s*子节点)"
)
_CONTROL_OR_WHITESPACE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")
_PUNCTUATION_RUN = re.compile(r"([，,；;。.!！？?])(?:\s*[，,；;。.!！？?])+")
_DANGLING_CONNECTOR = re.compile(
    r"(?:[，,；;]\s*)?(?:但是|但|并且|而且|同时|且|并)\s*$"
)

def _validate_operation_identifier(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("operation identifier must be nonblank and already trimmed")
    if len(value.encode("utf-8")) > 64:
        raise ValueError("operation identifier exceeds 64 UTF-8 bytes")
    return value


def _normalize_generated_query(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("operation query must be nonblank")
    if len(normalized.encode("utf-8")) > MAX_GENERATOR_QUERY_BYTES:
        raise ValueError("operation query exceeds 4096 UTF-8 bytes")
    return normalized


_OperationIdentifier = Annotated[str, AfterValidator(_validate_operation_identifier)]
_GeneratedQuery = Annotated[str, AfterValidator(_normalize_generated_query)]


class _LLMOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op_id: _OperationIdentifier
    query: _GeneratedQuery
    intent_type: Literal[
        "create_node",
        "modify_node",
        "generate_expression",
        "delete_node",
    ]
    depends_on: list[_OperationIdentifier] = Field(
        default_factory=list, max_length=100
    )
    target_from: _OperationIdentifier | None = None


class _LLMGenerateOperationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[_LLMOperation] = Field(min_length=1, max_length=100)


class OperationGenerator:
    """Generate and validate node-level operations from an LLM response."""

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._llm_gateway = llm_gateway or self._default_llm_gateway

    def generate(
        self, request: GenerateOperationsRequest
    ) -> GenerateOperationsResponse:
        if len(request.query.encode("utf-8")) > MAX_GENERATOR_QUERY_BYTES:
            raise ValueError("operation generation query exceeds 4096 UTF-8 bytes")

        try:
            node_index = build_node_index(request.target_tree)
        except ValueError as exc:
            raise ValueError(f"failed to summarize target tree: {exc}") from exc

        summary = self._build_target_tree_summary(node_index, request.query)
        try:
            payload = self._llm_gateway(request.query, summary)
        except Exception as exc:
            raise ValueError(f"operation generation gateway failed: {exc}") from exc

        if isinstance(payload, dict) and payload.get("operations") == []:
            raise ValueError("operation generation requires at least one operation")
        try:
            inbound = _LLMGenerateOperationsResponse.model_validate(
                payload, strict=True
            )
        except (ValidationError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid operation generation payload: {exc}") from exc

        generated_operations = [
            Operation.model_validate(operation.model_dump(mode="python"))
            for operation in inbound.operations
        ]

        original_ids = [operation.op_id for operation in generated_operations]
        duplicate_ids = {
            op_id for op_id, count in Counter(original_ids).items() if count > 1
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
            for operation in generated_operations
        ]

        try:
            validate_and_sort_operations(operations)
        except ValueError as exc:
            raise ValueError(f"invalid operation dependency graph: {exc}") from exc

        self._enrich_container_queries(operations)
        return GenerateOperationsResponse(operations=operations)

    @staticmethod
    def _build_target_tree_summary(
        node_index: dict[str, NodeLocateCandidate],
        query: str,
    ) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        candidates = islice(node_index.values(), MAX_TREE_SUMMARY_CANDIDATES)
        for candidate in candidates:
            item = candidate.model_dump(
                mode="json", exclude={"identity_field", "field_slot"}
            )
            for field_name in (
                "xml_name",
                "annotation",
                "parent_xml_name",
                "tree_node_type",
            ):
                item[field_name] = OperationGenerator._sanitize_summary_text(
                    item[field_name], MAX_SUMMARY_TEXT_LENGTH
                )
            for field_name in ("node_id", "jsonpath", "parent_node_id"):
                item[field_name] = OperationGenerator._sanitize_summary_text(
                    item[field_name], MAX_SUMMARY_PATH_LENGTH
                )
            prospective_summary = [*summary, item]
            prospective_json = json.dumps(
                prospective_summary, ensure_ascii=False
            )
            if (
                OperationGenerator._accounted_prompt_bytes(
                    query, prospective_json
                )
                > MAX_GENERATOR_PROMPT_BYTES
            ):
                break
            summary.append(item)
        return summary

    @staticmethod
    def _accounted_prompt_bytes(query: str, summary_json: str) -> int:
        return (
            GENERATOR_PROMPT_TEMPLATE_OVERHEAD_BYTES
            + GENERATOR_PROMPT_INPUT_OVERHEAD_BYTES
            + len(query.encode("utf-8"))
            + len(summary_json.encode("utf-8"))
        )

    @staticmethod
    def _sanitize_summary_text(value: Any, max_length: int) -> Any:
        if not isinstance(value, str):
            return value
        return _CONTROL_OR_WHITESPACE.sub(" ", value).strip()[:max_length]

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
