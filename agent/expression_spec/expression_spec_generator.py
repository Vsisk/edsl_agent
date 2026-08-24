from __future__ import annotations

import re
from typing import Any

from .models import (
    ExpressionContextSpec,
    MissingRequirement,
    ResourceBinding,
    SearchRequest,
    SearchResult,
    SpecDraft,
    SpecGenerationResult,
)


class ExpressionSpecGenerator:
    def generate(
        self,
        *,
        query: str,
        node: Any,
        draft: SpecDraft,
        search_requests: list[SearchRequest] | None = None,
        search_results: list[SearchResult],
        context: Any,
    ) -> SpecGenerationResult:
        del query, node
        requests_by_id = {
            request.request_id: request for request in (search_requests or [])
        }
        resolved_values = _collect_known_values(draft.known_values)
        resolved_values.update(_collect_context_values(context))

        for result in search_results:
            if not result.success or result.selected_resource is None:
                continue
            request = requests_by_id.get(result.request_id)
            introduced = request.introduced_by if request is not None else None
            selected = result.selected_resource
            if introduced and introduced.get("param"):
                resolved_values[_norm(introduced["param"])] = _resource_value(selected)
            expected_return_type = (
                request.expected_return_type if request is not None else None
            )
            if expected_return_type:
                resolved_values.setdefault(_norm(expected_return_type), _resource_value(selected))

        resources: dict[str, ResourceBinding] = {}
        missing: list[MissingRequirement] = []
        missing_keys = set()
        for result in search_results:
            if not result.success or result.selected_resource is None:
                continue
            request = requests_by_id.get(result.request_id)
            selected = result.selected_resource
            params = {}
            for param in _params(selected):
                name = str(param.get("name") or param.get("param_name") or "").strip()
                if not name:
                    continue
                resolved = _resolve_param(name, param, resolved_values)
                if resolved is None:
                    key = (request.requirement_id if request else "", name)
                    if key not in missing_keys:
                        missing_keys.add(key)
                        missing.append(
                            MissingRequirement(
                                requirement_id=(
                                    request.requirement_id if request else result.request_id
                                ),
                                semantic=name,
                                resource_types=["context"],
                                expected_return_type=_param_type(param),
                                scope=request.scope if request is not None else None,
                                introduced_by={
                                    "resource": selected.get("resource_id"),
                                    "param": name,
                                },
                            )
                        )
                    continue
                params[name] = resolved
                resolved_values.setdefault(_norm(name), resolved)
            resources[result.request_id] = ResourceBinding(
                source_type=_source_type(selected),
                resource_id=selected.get("resource_id"),
                params=params,
                return_field=selected.get("return_field"),
                cardinality=_cardinality(selected),
            )

        if missing:
            return SpecGenerationResult(
                closed=False,
                missing_requirements=missing,
                resolved_values=resolved_values,
            )
        return SpecGenerationResult(
            closed=True,
            spec=ExpressionContextSpec(
                target=draft.target,
                logic_requirements=draft.logic_requirements,
                resources=resources,
            ),
            resolved_values=resolved_values,
        )


def _collect_known_values(values: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in values.items():
        result[_norm(key)] = value
    return result


def _collect_context_values(context: Any) -> dict[str, Any]:
    if context is None:
        return {}
    if hasattr(context, "model_dump"):
        context = context.model_dump(mode="json")
    if not isinstance(context, dict):
        return {}
    result = {}
    for key, value in context.items():
        if isinstance(value, str):
            result[_norm(key)] = value
        elif isinstance(value, dict):
            resource_id = value.get("resource_id") or value.get("context_name")
            if resource_id:
                result[_norm(key)] = resource_id
    return result


def _params(selected: dict[str, Any]) -> list[dict[str, Any]]:
    params = selected.get("params")
    if params is None:
        params = selected.get("param_list")
    return [item for item in params or [] if isinstance(item, dict)]


def _resolve_param(
    name: str,
    param: dict[str, Any],
    resolved_values: dict[str, Any],
) -> Any | None:
    for key in _param_keys(name, param):
        if key in resolved_values:
            return resolved_values[key]
    return None


def _param_keys(name: str, param: dict[str, Any]) -> list[str]:
    values = [
        name,
        _param_type(param),
        str(param.get("semantic") or ""),
    ]
    normalized = []
    for value in values:
        key = _norm(value)
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def _param_type(param: dict[str, Any]) -> str | None:
    value = param.get("data_type_name") or param.get("data_type") or param.get("type")
    return str(value) if value else None


def _source_type(selected: dict[str, Any]) -> str:
    value = selected.get("resource_type") or selected.get("source_type") or "context"
    if value in {"context", "function", "bo", "naming_sql", "literal"}:
        return value
    return "context"


def _resource_value(selected: dict[str, Any]) -> Any:
    return selected.get("resource_id") or selected.get("context_name") or selected


def _cardinality(selected: dict[str, Any]) -> str | None:
    if selected.get("cardinality"):
        return str(selected["cardinality"])
    return_type = selected.get("return_type")
    if isinstance(return_type, dict) and return_type.get("is_list") is not None:
        return "list" if return_type.get("is_list") else "single"
    return None


def _norm(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z_\u4e00-\u9fff]+", "", str(value or "")).lower()
