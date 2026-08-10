from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.context_pack import ContextPack, ContextPackPromptRenderer
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.expression_generation.expression_spec import ExpressionSpec
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.models import LEGACY_PLAN_SCHEMA, Plan

MAX_SUMMARY_TEXT = 512
MAX_SUMMARY_ITEMS = 100
MAX_INVALID_PLAN_EXCERPT = 12_000
MAX_ERROR_EXCERPT = 2_000
MAX_RESOURCES_JSON_CHARS = 60_000
MAX_SELECTION_BO_NAME = 512
MAX_SELECTION_SQL_NAME = 512
MAX_SELECTION_PARAM_NAME = 256
MAX_SELECTION_SOURCE_REF = 1_024
MAX_SELECTION_EVIDENCE_ITEMS = 20
MAX_SELECTION_EVIDENCE_SOURCE = 128
MAX_SELECTION_EVIDENCE_ACTION = 128
MAX_SELECTION_EVIDENCE_TEXT = 512


class LLMPlanner:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def plan(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        filtered_env: FilteredEnvironment,
        typed_context: TypedExpressionContext | None = None,
        context_pack: ContextPack | None = None,
        expression_spec: ExpressionSpec | None = None,
        retry_feedback: dict[str, Any] | None = None,
    ) -> Plan:
        if not self.is_usable:
            raise RuntimeError("LLM planner is not usable")

        resources = _summarize_filtered_environment(filtered_env)
        resources["context_pack"] = (
            json.loads(ContextPackPromptRenderer().render_json(context_pack)) if context_pack else {}
        )
        resources_json = _dump_json(resources)
        typed_context_json = _summarize_typed_context_json(typed_context)
        expression_scope_json = _summarize_expression_scope_json(expression_spec)
        expression_skills_json = _summarize_expression_skills_json(expression_spec)
        node_info_json = _dump_json(_summarize_node(node_info))
        plan_schema_json = _dump_json(LEGACY_PLAN_SCHEMA)

        try:
            response = generate_by_llm(
                prompt_template="planner",
                llm_name="base",
                lang="zh",
                client=self.client,
                user_requirement=user_query,
                node_info_json=node_info_json,
                resources_json=resources_json,
                typed_context_json=typed_context_json,
                expression_scope_json=expression_scope_json,
                expression_skills_json=expression_skills_json,
                plan_schema_json=plan_schema_json,
                retry_feedback_json=_dump_json(retry_feedback or {}),
            )
            plan = Plan.model_validate(response)
            return plan
        except (ValueError, ValidationError) as exc:
            invalid_plan_json = _invalid_plan_diagnostic(locals().get("response", {}))
            return self._repair(
                node_info=node_info,
                user_query=user_query,
                resources_json=resources_json,
                typed_context_json=typed_context_json,
                expression_scope_json=expression_scope_json,
                expression_skills_json=expression_skills_json,
                node_info_json=node_info_json,
                plan_schema_json=plan_schema_json,
                invalid_plan_json=invalid_plan_json,
                error_message=_error_diagnostic(exc),
                naming_sql_selection=filtered_env.naming_sql_selection,
                retry_feedback_json=_dump_json(retry_feedback or {}),
            )

    def _repair(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        resources_json: str,
        typed_context_json: str,
        expression_scope_json: str,
        expression_skills_json: str,
        node_info_json: str,
        plan_schema_json: str,
        invalid_plan_json: str,
        error_message: str,
        naming_sql_selection: list[Any],
        retry_feedback_json: str,
    ) -> Plan:
        response = generate_by_llm(
            prompt_template="planner_repair",
            llm_name="base",
            lang="zh",
            client=self.client,
            user_requirement=user_query,
            node_info_json=node_info_json,
            resources_json=resources_json,
            typed_context_json=typed_context_json,
            expression_scope_json=expression_scope_json,
            expression_skills_json=expression_skills_json,
            plan_schema_json=plan_schema_json,
            invalid_plan_json=invalid_plan_json,
            error_message=error_message,
            retry_feedback_json=retry_feedback_json,
        )
        plan = Plan.model_validate(response)
        return plan


def _summarize_node(node_info: NodeDef) -> dict[str, Any]:
    return {
        "node_id": _summary_text(node_info.node_id),
        "node_path": _summary_text(node_info.node_path),
        "node_name": _summary_text(node_info.node_name),
        "description": _summary_text(node_info.description),
    }


def _summarize_filtered_environment(filtered_env: FilteredEnvironment) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "global_context": [],
        "local_context": [],
        "bo": [],
        "function": [],
    }
    selection = filtered_env.naming_sql_selection
    if selection:
        summary["naming_sql_selection"] = _summarize_naming_sql_selection(selection)
        if len(_dump_json(summary)) > MAX_RESOURCES_JSON_CHARS:
            raise ValueError("NAMING_SQL_SELECTION_TOO_LARGE")

    groups = (
        ("global_context", filtered_env.selected_global_contexts, _summarize_context),
        ("local_context", filtered_env.visible_local_context, _summarize_context),
        ("bo", filtered_env.selected_bos, _summarize_bo),
        ("function", filtered_env.selected_functions, _summarize_function),
    )
    for group_name, resources, summarize in groups:
        for resource in resources[:MAX_SUMMARY_ITEMS]:
            item = summarize(resource)
            if selection and group_name == "bo":
                item.pop("naming_sql", None)
            summary[group_name].append(item)
            if len(_dump_json(summary)) > MAX_RESOURCES_JSON_CHARS:
                summary[group_name].pop()
    return summary


def _summarize_filtered_environment_json(filtered_env: FilteredEnvironment) -> str:
    return _dump_json(_summarize_filtered_environment(filtered_env))


def _summarize_typed_context_json(
    typed_context: TypedExpressionContext | None,
) -> str:
    context = typed_context or TypedExpressionContext()
    value = {
        "Root Values": [
            root.model_dump(
                mode="json",
                exclude={
                    "methods": True,
                    "fields": {"__all__": {"methods"}},
                },
            )
            for root in context.root_values
        ],
        "Suggested Vars": [
            template.model_dump(
                mode="json",
                exclude={
                    "available_fields": {"__all__": {"methods"}},
                },
            )
            for template in context.var_templates
        ],
        "Available Methods by Type": _prompt_method_catalog(context),
        "Expression Patterns": [
            pattern.model_dump(mode="json")
            for pattern in context.expression_patterns
        ],
        "Warnings": list(context.warnings),
    }
    return _dump_json(value)


def _prompt_method_catalog(context: TypedExpressionContext) -> list[dict[str, Any]]:
    methods_by_type: dict[str, list[str]] = {}

    def add(owner_type: str, methods: list[str]) -> None:
        if not methods:
            return
        collected = methods_by_type.setdefault(owner_type, [])
        for method in methods:
            if method not in collected:
                collected.append(method)

    for view in context.method_catalog:
        add(view.owner_type, view.methods)
    for root in context.root_values:
        add(root.return_type, root.methods)
        for field in root.fields:
            add(field.return_type, field.methods)
    for template in context.var_templates:
        for field in template.available_fields:
            add(field.return_type, field.methods)

    return [
        {"owner_type": owner_type, "methods": methods}
        for owner_type, methods in methods_by_type.items()
    ]


def _summarize_expression_scope_json(
    expression_spec: ExpressionSpec | None,
) -> str:
    if expression_spec is None:
        return "{}"
    return _dump_json(_bounded_typed_value(asdict(expression_spec.scope_context)))


def _summarize_expression_skills_json(
    expression_spec: ExpressionSpec | None,
) -> str:
    if expression_spec is None:
        return "[]"
    values = [
        {
            "skill_id": _summary_text(item.skill_id),
            "title": _summary_text(item.title),
            "markdown": str(item.markdown or "")[:4000],
        }
        for item in expression_spec.skill_instructions[:20]
    ]
    return _dump_json(values)


def _bounded_typed_value(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, str):
        return _summary_text(value)
    if isinstance(value, dict):
        return {
            _summary_text(key): _bounded_typed_value(item, depth + 1)
            for key, item in list(value.items())[:MAX_SUMMARY_ITEMS]
        }
    if isinstance(value, list):
        return [
            _bounded_typed_value(item, depth + 1)
            for item in value[:MAX_SUMMARY_ITEMS]
        ]
    return value if isinstance(value, (int, float, bool)) or value is None else _summary_text(value)


def _summarize_naming_sql_selection(selection: Any) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "bo": _selection_text(profile.bo_name, MAX_SELECTION_BO_NAME),
                "name": _selection_text(profile.namingsql_name, MAX_SELECTION_SQL_NAME),
                "where_conditions": [
                    _selection_text(value, MAX_SUMMARY_TEXT)
                    for value in profile.where_conditions
                ],
                "return_fields": [
                    _selection_text(value, MAX_SELECTION_PARAM_NAME)
                    for value in profile.return_fields
                ],
                "performance_optimized": profile.performance_optimized,
            }
            for profile in selection[:20]
        ]
    }


def _safe_evidence_text(value: Any, limit: int) -> str:
    """Normalize control characters and truncate untrusted decision evidence."""
    return " ".join(str(value or "").split())[:limit]


def _selection_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) > limit or _has_control(text):
        raise ValueError("NAMING_SQL_SELECTION_TOO_LARGE")
    return text


def _bounded_json_value(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        return None
    if isinstance(value, str):
        return _selection_text(value, MAX_SUMMARY_TEXT)
    if isinstance(value, dict):
        return {_selection_text(key, 128): _bounded_json_value(item, depth + 1)
                for key, item in list(value.items())[:MAX_SUMMARY_ITEMS]}
    if isinstance(value, list):
        return [_bounded_json_value(item, depth + 1) for item in value[:MAX_SUMMARY_ITEMS]]
    return value if isinstance(value, (int, float, bool)) or value is None else _selection_text(value, MAX_SUMMARY_TEXT)


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _summarize_context(resource: Any) -> dict[str, Any]:
    context_name = _summary_text(getattr(resource, "context_name", ""))
    return_type = getattr(resource, "return_type", None)
    return {
        "resource_id": _summary_text(getattr(resource, "resource_id", "")),
        "path": context_name,
        "name": context_name,
        "annotation": _summary_text(getattr(resource, "annotation", "")),
        "return_type": _summary_text(getattr(return_type, "data_type_name", None)),
    }


def _summarize_bo(resource: Any) -> dict[str, Any]:
    return {
        "resource_id": _summary_text(getattr(resource, "resource_id", "")),
        "bo": _summary_text(getattr(resource, "bo_name", "")),
        "description": _summary_text(getattr(resource, "bo_desc", "")),
        "properties": [
            {
                "field_name": _summary_text(item.field_name),
                "description": _summary_text(item.description),
                "data_type_name": _summary_text(item.data_type_name),
            }
            for item in (getattr(resource, "property_list", []) or [])[:MAX_SUMMARY_ITEMS]
        ],
        "naming_sql": [
            {
                "name": _summary_text(item.sql_name),
                "description": _summary_text(item.sql_description),
                "params": [
                    {
                        "name": _summary_text(param.param_name),
                        "data_type_name": _summary_text(param.data_type_name),
                    }
                    for param in item.param_list[:MAX_SUMMARY_ITEMS]
                ],
            }
            for item in (getattr(resource, "naming_sql_list", []) or [])[:MAX_SUMMARY_ITEMS]
        ],
    }


def _summarize_function(resource: Any) -> dict[str, Any]:
    return_type = getattr(resource, "return_type", None)
    func_name = _summary_text(getattr(resource, "func_name", ""))
    func_class = _summary_text(getattr(resource, "func_class", ""))
    qualified_name = f"{func_class}.{func_name}" if func_class and func_name else func_name
    return {
        "resource_id": _summary_text(getattr(resource, "resource_id", "")),
        "name": qualified_name,
        "description": _summary_text(getattr(resource, "func_desc", "")),
        "class": func_class,
        "params": [
            {
                "name": _summary_text(item.param_name),
                "data_type_name": _summary_text(item.data_type_name),
            }
            for item in (getattr(resource, "param_list", []) or [])[:MAX_SUMMARY_ITEMS]
        ],
        "return_type": _summary_text(getattr(return_type, "data_type_name", None)),
    }


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _summary_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_SUMMARY_TEXT]


def _invalid_plan_diagnostic(value: Any) -> str:
    try:
        rendered = _dump_json(value)
    except (TypeError, ValueError, RecursionError):
        rendered = repr(type(value).__name__)
    normalized = " ".join(rendered.split())
    return _dump_json(
        {
            "excerpt": normalized[:MAX_INVALID_PLAN_EXCERPT],
            "truncated": len(normalized) > MAX_INVALID_PLAN_EXCERPT,
        }
    )


def _error_diagnostic(error: Exception) -> str:
    normalized = " ".join(str(error).split())
    return _dump_json(
        {
            "message": normalized[:MAX_ERROR_EXCERPT],
            "truncated": len(normalized) > MAX_ERROR_EXCERPT,
        }
    )
