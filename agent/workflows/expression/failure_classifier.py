from __future__ import annotations

from enum import Enum
from typing import Any

from agent.workflow.runtime.stage_result import Observation, ObservationSeverity


class ExpressionObservationCode(str, Enum):
    SPEC_INSUFFICIENT = "SPEC_INSUFFICIENT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_SCHEMA_MISMATCH = "RESOURCE_SCHEMA_MISMATCH"
    RESOURCE_CHAIN_BROKEN = "RESOURCE_CHAIN_BROKEN"
    UNKNOWN_PROPERTY = "UNKNOWN_PROPERTY"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    FUNCTION_ARGUMENT_ERROR = "FUNCTION_ARGUMENT_ERROR"
    SEMANTIC_MISMATCH = "SEMANTIC_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ExpressionFailureClassifier:
    def classify_spec_failure(
        self,
        *,
        source_stage: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        missing_information: list[str] | None = None,
    ) -> Observation:
        return Observation(
            code=ExpressionObservationCode.SPEC_INSUFFICIENT.value,
            source_stage=source_stage,
            message=message,
            evidence=evidence or {},
            missing_information=missing_information or [],
            related_artifacts=["spec"],
            retryable=True,
            severity=ObservationSeverity.ERROR,
        )

    def classify_resource_failure(
        self,
        *,
        source_stage: str,
        error: Any,
        related_artifacts: list[str] | None = None,
    ) -> Observation:
        payload = _coerce_error_payload(error)
        raw_code = _upper(payload.get("code") or payload.get("error_type"))
        message = _message(payload, error)
        normalized = _normalize_text(" ".join([raw_code, message]))
        if any(token in normalized for token in ("not found", "missing", "no candidate", "empty result")):
            code = ExpressionObservationCode.RESOURCE_NOT_FOUND
            missing_information = _missing_information(payload, default=["resource"])
        elif any(token in normalized for token in ("schema", "shape", "field type", "metadata mismatch")):
            code = ExpressionObservationCode.RESOURCE_SCHEMA_MISMATCH
            missing_information = _missing_information(payload)
        elif any(token in normalized for token in ("chain", "path", "unreachable", "broken")):
            code = ExpressionObservationCode.RESOURCE_CHAIN_BROKEN
            missing_information = _missing_information(payload, default=["resource_chain"])
        else:
            code = ExpressionObservationCode.SEMANTIC_MISMATCH
            missing_information = _missing_information(payload)
        return Observation(
            code=code.value,
            source_stage=source_stage,
            message=message,
            evidence=payload,
            missing_information=missing_information,
            related_artifacts=related_artifacts or ["resources"],
            retryable=True,
            severity=ObservationSeverity.ERROR,
        )

    def classify_generation_failure(
        self,
        *,
        source_stage: str,
        error: Any,
        related_artifacts: list[str] | None = None,
    ) -> Observation:
        payload = _coerce_error_payload(error)
        raw_code = _upper(payload.get("code") or payload.get("error_type"))
        message = _message(payload, error)
        code = _classify_expression_error(raw_code=raw_code, message=message)
        return Observation(
            code=code.value,
            source_stage=source_stage,
            message=message,
            evidence=payload,
            missing_information=_missing_information(payload),
            related_artifacts=related_artifacts or ["spec", "resources", "typed_context"],
            retryable=True,
            severity=ObservationSeverity.ERROR,
        )

    def classify_ast_failure(
        self,
        *,
        source_stage: str,
        validation_result: Any,
        related_artifacts: list[str] | None = None,
    ) -> Observation:
        errors = _validation_errors(validation_result)
        primary = errors[0] if errors else {}
        raw_code = _upper(primary.get("code") or primary.get("error_type"))
        message = _message(primary, validation_result)
        code = _classify_expression_error(raw_code=raw_code, message=message)
        return Observation(
            code=code.value,
            source_stage=source_stage,
            message=message,
            evidence={
                "primary_error": primary,
                "errors": errors,
                "is_valid": getattr(validation_result, "is_valid", None),
            },
            missing_information=_missing_information(primary),
            related_artifacts=related_artifacts or ["ast", "validation", "typed_context", "resources"],
            retryable=True,
            severity=ObservationSeverity.ERROR,
        )

    def classify_internal_error(
        self,
        *,
        source_stage: str,
        error: Exception,
        related_artifacts: list[str] | None = None,
    ) -> Observation:
        return Observation(
            code=ExpressionObservationCode.INTERNAL_ERROR.value,
            source_stage=source_stage,
            message=str(error),
            evidence={"error_type": type(error).__name__},
            missing_information=[],
            related_artifacts=related_artifacts or [],
            retryable=False,
            severity=ObservationSeverity.FATAL,
        )


def _classify_expression_error(
    *,
    raw_code: str,
    message: str,
) -> ExpressionObservationCode:
    normalized = _normalize_text(" ".join([raw_code, message]))
    if any(token in normalized for token in ("unknown property", "unknown field", "property_not_found", "field_not_found")):
        return ExpressionObservationCode.UNKNOWN_PROPERTY
    if any(token in normalized for token in ("unknown function", "unknown method", "function_not_found", "method_not_found")):
        return ExpressionObservationCode.FUNCTION_ARGUMENT_ERROR
    if any(token in normalized for token in ("argument", "parameter", "arity", "arg_count", "wrong number")):
        return ExpressionObservationCode.FUNCTION_ARGUMENT_ERROR
    if any(token in normalized for token in ("return type", "target_return_type_mismatch", "type mismatch", "if_branch_type_mismatch")):
        return ExpressionObservationCode.TYPE_MISMATCH
    if any(token in normalized for token in ("syntax", "parse", "parser", "invalid token", "unexpected token")):
        return ExpressionObservationCode.SYNTAX_ERROR
    if any(token in normalized for token in ("semantic", "meaning", "intent", "goal mismatch")):
        return ExpressionObservationCode.SEMANTIC_MISMATCH
    return ExpressionObservationCode.SEMANTIC_MISMATCH


def _validation_errors(validation_result: Any) -> list[dict[str, Any]]:
    if isinstance(validation_result, dict) and "errors" in validation_result:
        errors = validation_result.get("errors")
        if isinstance(errors, list):
            return [_coerce_error_payload(error) for error in errors]
        if errors is not None:
            return [_coerce_error_payload(errors)]
        return []
    errors = getattr(validation_result, "errors", validation_result)
    if errors is None:
        return []
    if isinstance(errors, dict):
        return [errors]
    if isinstance(errors, list):
        return [_coerce_error_payload(error) for error in errors]
    return [_coerce_error_payload(errors)]


def _coerce_error_payload(error: Any) -> dict[str, Any]:
    if isinstance(error, dict):
        return dict(error)
    if hasattr(error, "model_dump"):
        return error.model_dump(mode="json")
    payload: dict[str, Any] = {}
    for name in (
        "code",
        "error_type",
        "message",
        "field",
        "property",
        "function",
        "method",
        "expected_type",
        "actual_type",
        "expected",
        "actual",
        "token",
        "expr",
    ):
        if hasattr(error, name):
            payload[name] = getattr(error, name)
    if payload:
        return payload
    return {"message": str(error)}


def _message(payload: dict[str, Any], fallback: Any) -> str:
    value = payload.get("message")
    if value is not None and str(value).strip():
        return str(value)
    return str(fallback)


def _missing_information(
    payload: dict[str, Any],
    *,
    default: list[str] | None = None,
) -> list[str]:
    value = payload.get("missing_information")
    if isinstance(value, list):
        return [str(item) for item in value]
    result = []
    for key in ("field", "property", "function", "method", "expected_type", "actual_type"):
        if payload.get(key) is not None:
            result.append(f"{key}:{payload[key]}")
    return result or list(default or [])


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_text(value: Any) -> str:
    return str(value or "").replace("_", " ").replace("-", " ").strip().lower()
