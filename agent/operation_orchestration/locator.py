from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from agent.llm.generate_by_llm import generate_by_llm
from agent.operation_orchestration.models import (
    LocateOperationRequest,
    LocateOperationResponse,
    Operation,
)
from agent.operation_orchestration.node_index import build_node_index, is_valid_candidate


LLMGateway = Callable[[str, str, list[dict[str, Any]]], dict[str, Any]]
MAX_PROMPT_CANDIDATES = 200
MAX_PROMPT_BYTES = 32_000
MAX_QUERY_BYTES = 4_096
MAX_NODE_ID_BYTES = 256
MAX_JSONPATH_BYTES = 2_048
PROMPT_OVERHEAD_BYTES = 4_096
MAX_DESCRIPTION_LENGTH = 256
_DESCRIPTION_FIELDS = ("xml_name", "annotation", "parent_xml_name")
_CONTROL_OR_WHITESPACE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")
_VerbatimNonBlankText = Annotated[str, StringConstraints(min_length=1)]
_DescriptiveNonBlankText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]


class LocationSelection(BaseModel):
    """Strict, untrusted inbound selection returned by the locator gateway."""

    model_config = ConfigDict(extra="forbid")

    selected_node_id: _VerbatimNonBlankText
    selected_jsonpath: _VerbatimNonBlankText
    confidence: Literal["high", "medium", "low"]
    reason: _DescriptiveNonBlankText

    @field_validator("selected_node_id", "selected_jsonpath", mode="before")
    @classmethod
    def require_verbatim_trimmed_text(cls, value: Any) -> Any:
        if isinstance(value, str) and value != value.strip():
            raise ValueError("value must already be trimmed")
        return value


class OperationLocator:
    """Locate an independent operation using a constrained candidate gateway.

    Injected gateways receive ``(query, intent_type, candidates)`` for each bounded
    DFS chunk. Candidate IDs and paths are exact; descriptive fields are sanitized
    prompt copies and cannot mutate the authoritative candidate snapshots.
    """

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._llm_gateway = llm_gateway or self._default_llm_gateway

    def locate(self, request: LocateOperationRequest) -> LocateOperationResponse:
        operation = request.operation.model_copy(
            deep=True,
            update={
                "target_node_id": None,
                "target_jsonpath": None,
                "output_node_id": None,
                "status": "pending",
                "error_message": None,
            },
        )

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

        candidates = tuple(
            deepcopy(candidate.model_dump(mode="json"))
            for candidate in node_index.values()
            if is_valid_candidate(operation.intent_type, candidate)
        )
        if not candidates:
            return self._failure(
                operation,
                candidates,
                f"no valid candidates for intent {operation.intent_type}",
            )

        structural_error = self._validate_structural_limits(
            operation.query, candidates
        )
        if structural_error is not None:
            return self._fallback_or_failure(
                operation, candidates, structural_error
            )

        round_candidates = candidates
        all_errors: list[str] = []
        while True:
            try:
                chunks = self._candidate_chunks(
                    round_candidates, operation.query, operation.intent_type
                )
            except ValueError as exc:
                return self._fallback_or_failure(operation, candidates, str(exc))

            winners: list[dict[str, Any]] = []
            round_errors: list[str] = []
            for authoritative_chunk, prompt_chunk in chunks:
                try:
                    winner = self._select_chunk(
                        operation.query,
                        operation.intent_type,
                        authoritative_chunk,
                        prompt_chunk,
                    )
                    winners.append(winner)
                except Exception as exc:
                    round_errors.append(str(exc))

            all_errors.extend(round_errors)
            if not winners:
                reason = "; ".join(all_errors) or "no valid semantic selection"
                return self._fallback_or_failure(operation, candidates, reason)
            if len(winners) == 1:
                return self._success(operation, candidates, winners[0])
            if len(winners) >= len(round_candidates):
                return self._fallback_or_failure(
                    operation,
                    candidates,
                    "semantic tournament did not reduce candidate count",
                )
            round_candidates = tuple(winners)

    def _select_chunk(
        self,
        query: str,
        intent_type: str,
        authoritative_chunk: tuple[dict[str, Any], ...],
        prompt_chunk: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._llm_gateway(query, intent_type, deepcopy(prompt_chunk))
        selection = LocationSelection.model_validate(payload, strict=True)
        if selection.confidence == "low":
            raise ValueError("locator returned low confidence")

        selected = next(
            (
                candidate
                for candidate in authoritative_chunk
                if candidate["node_id"] == selection.selected_node_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("selected node_id is not a supplied candidate")
        if selected["jsonpath"] != selection.selected_jsonpath:
            raise ValueError("selected jsonpath does not match the selected candidate")
        return selected

    @staticmethod
    def _validate_structural_limits(
        query: str, candidates: tuple[dict[str, Any], ...]
    ) -> str | None:
        if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
            return f"query exceeds {MAX_QUERY_BYTES} UTF-8 bytes"
        for candidate in candidates:
            if len(candidate["node_id"].encode("utf-8")) > MAX_NODE_ID_BYTES:
                return f"candidate node_id exceeds {MAX_NODE_ID_BYTES} UTF-8 bytes"
            if len(candidate["jsonpath"].encode("utf-8")) > MAX_JSONPATH_BYTES:
                return f"candidate jsonpath exceeds {MAX_JSONPATH_BYTES} UTF-8 bytes"
        return None

    @classmethod
    def _candidate_chunks(
        cls,
        candidates: tuple[dict[str, Any], ...],
        query: str,
        intent_type: str,
    ) -> list[tuple[tuple[dict[str, Any], ...], list[dict[str, Any]]]]:
        chunks: list[
            tuple[tuple[dict[str, Any], ...], list[dict[str, Any]]]
        ] = []
        authoritative_chunk: list[dict[str, Any]] = []
        prompt_chunk: list[dict[str, Any]] = []

        for candidate in candidates:
            prompt_candidate = cls._prompt_candidate(candidate)
            proposed_prompt_chunk = [*prompt_chunk, prompt_candidate]
            exceeds_count = len(proposed_prompt_chunk) > MAX_PROMPT_CANDIDATES
            exceeds_bytes = (
                cls._prompt_size(proposed_prompt_chunk, query, intent_type)
                > MAX_PROMPT_BYTES
            )
            if prompt_chunk and (exceeds_count or exceeds_bytes):
                chunks.append((tuple(authoritative_chunk), prompt_chunk))
                authoritative_chunk = []
                prompt_chunk = []
            if not prompt_chunk and (
                cls._prompt_size([prompt_candidate], query, intent_type)
                > MAX_PROMPT_BYTES
            ):
                raise ValueError("single candidate exceeds locator prompt budget")
            authoritative_chunk.append(candidate)
            prompt_chunk.append(prompt_candidate)

        if prompt_chunk:
            chunks.append((tuple(authoritative_chunk), prompt_chunk))
        return chunks

    @staticmethod
    def _prompt_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
        prompt_candidate = deepcopy(candidate)
        for field_name in _DESCRIPTION_FIELDS:
            value = prompt_candidate.get(field_name)
            if isinstance(value, str):
                prompt_candidate[field_name] = _CONTROL_OR_WHITESPACE.sub(
                    " ", value
                ).strip()[:MAX_DESCRIPTION_LENGTH]
        return prompt_candidate

    @staticmethod
    def _prompt_size(
        candidates: list[dict[str, Any]], query: str, intent_type: str
    ) -> int:
        return (
            len(json.dumps(candidates, ensure_ascii=False).encode("utf-8"))
            + len(query.encode("utf-8"))
            + len(intent_type.encode("utf-8"))
            + PROMPT_OVERHEAD_BYTES
        )

    @staticmethod
    def _success(
        operation: Operation,
        candidates: tuple[dict[str, Any], ...],
        selected: dict[str, Any],
        response_error_message: str | None = None,
    ) -> LocateOperationResponse:
        operation.target_node_id = selected["node_id"]
        operation.target_jsonpath = selected["jsonpath"]
        operation.status = "located"
        operation.error_message = None
        return LocateOperationResponse(
            success=True,
            operation=operation,
            candidates=deepcopy(list(candidates)),
            error_message=response_error_message,
        )

    def _fallback_or_failure(
        self,
        operation: Operation,
        candidates: tuple[dict[str, Any], ...],
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
                return self._success(
                    operation,
                    candidates,
                    root_candidate,
                    "semantic location failed; used create root fallback",
                )
            reason = f"create fallback found no valid root candidate: {reason}"
        return self._failure(
            operation, candidates, f"operation location failed: {reason}"
        )

    @staticmethod
    def _failure(
        operation: Operation,
        candidates: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        message: str,
    ) -> LocateOperationResponse:
        operation.status = "failed"
        operation.error_message = message
        return LocateOperationResponse(
            success=False,
            operation=operation,
            candidates=deepcopy(list(candidates)),
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
