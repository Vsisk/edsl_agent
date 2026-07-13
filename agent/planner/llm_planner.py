from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.context_pack import ContextPack, ContextPackPromptRenderer
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.models import LEGACY_PLAN_SCHEMA, Plan
from agent.naming_sql_selector.plan_validator import validate_naming_sql_plan

if TYPE_CHECKING:
    from agent.naming_sql_selector.models import NamingSqlSelectResponse

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
MAX_TYPED_CONTEXT_JSON_CHARS = 60_000


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
    ) -> Plan:
        if not self.is_usable:
            raise RuntimeError("LLM planner is not usable")

        resources = _summarize_filtered_environment(filtered_env)
        resources["context_pack"] = (
            json.loads(ContextPackPromptRenderer().render_json(context_pack)) if context_pack else {}
        )
        resources_json = _dump_json(resources)
        typed_context_json = _summarize_typed_context_json(typed_context)
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
                plan_schema_json=plan_schema_json,
            )
            plan = Plan.model_validate(response)
            if filtered_env.naming_sql_selection is not None:
                validate_naming_sql_plan(plan, filtered_env.naming_sql_selection)
            return plan
        except (ValueError, ValidationError) as exc:
            invalid_plan_json = _invalid_plan_diagnostic(locals().get("response", {}))
            return self._repair(
                node_info=node_info,
                user_query=user_query,
                resources_json=resources_json,
                typed_context_json=typed_context_json,
                node_info_json=node_info_json,
                plan_schema_json=plan_schema_json,
                invalid_plan_json=invalid_plan_json,
                error_message=_error_diagnostic(exc),
                naming_sql_selection=filtered_env.naming_sql_selection,
            )

    def _repair(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        resources_json: str,
        typed_context_json: str,
        node_info_json: str,
        plan_schema_json: str,
        invalid_plan_json: str,
        error_message: str,
        naming_sql_selection: NamingSqlSelectResponse | None,
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
            plan_schema_json=plan_schema_json,
            invalid_plan_json=invalid_plan_json,
            error_message=error_message,
        )
        plan = Plan.model_validate(response)
        if naming_sql_selection is not None:
            validate_naming_sql_plan(plan, naming_sql_selection)
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
    if selection is not None:
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
            if selection is not None and group_name == "bo":
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
        "Root Values": context.root_values,
        "Suggested Vars": context.var_templates,
        "Available Methods by Type": context.method_catalog,
        "Expression Patterns": context.expression_patterns,
        "Warnings": context.warnings,
    }
    rendered = _dump_json(_bounded_typed_value(value))
    if len(rendered) > MAX_TYPED_CONTEXT_JSON_CHARS:
        raise ValueError("TYPED_EXPRESSION_CONTEXT_TOO_LARGE")
    return rendered


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
    if not selection.success:
        raise ValueError("NAMING_SQL_SELECTION_FAILED")
    candidates = []
    for candidate in selection.candidates[:20]:
        candidates.append({
            "bo": _selection_text(candidate.bo_name, MAX_SELECTION_BO_NAME),
            "id": _selection_text(candidate.naming_sql_id, MAX_SELECTION_SQL_NAME),
            "name": _selection_text(candidate.naming_sql_name, MAX_SELECTION_SQL_NAME),
            "rank": candidate.rank,
            "params": [
                {
                    "name": _selection_text(item.get("param_name") or item.get("name"), MAX_SELECTION_PARAM_NAME),
                    "type": _selection_text(item.get("data_type_name") or item.get("data_type"), MAX_SELECTION_PARAM_NAME),
                }
                for item in candidate.param_list[:MAX_SUMMARY_ITEMS] if isinstance(item, dict)
            ],
            "return_type": _bounded_json_value(candidate.return_type),
            "evidence": [_selection_text(item, MAX_SUMMARY_TEXT) for item in candidate.evidence[:10]],
        })
    hints = [{
        "semantic_name": _selection_text(hint.semantic_name, MAX_SUMMARY_TEXT),
        "expected_data_type": _selection_text(hint.expected_data_type, MAX_SUMMARY_TEXT),
        "expected_data_type_name": _selection_text(hint.expected_data_type_name, MAX_SUMMARY_TEXT),
        "source_hint": _selection_text(hint.source_hint, MAX_SUMMARY_TEXT),
        "candidate_context_paths": [_selection_text(path, MAX_SELECTION_SOURCE_REF) for path in hint.candidate_context_paths[:20]],
    } for hint in selection.context_requirements_hint[:MAX_SUMMARY_ITEMS]]
    constraints = selection.selection_constraints
    return {
        "candidates": candidates,
        "hints": hints,
        "constraints": None if constraints is None else {
            "allowed_bo_names": [_selection_text(value, MAX_SELECTION_BO_NAME) for value in constraints.allowed_bo_names[:20]],
            "allowed_naming_sql_ids": [_selection_text(value, MAX_SELECTION_SQL_NAME) for value in constraints.allowed_naming_sql_ids[:20]],
            "max_candidates": constraints.max_candidates,
        },
        "evidence_trace": [{
            "source": _safe_evidence_text(item.source, MAX_SELECTION_EVIDENCE_SOURCE),
            "action": _safe_evidence_text(item.action, MAX_SELECTION_EVIDENCE_ACTION),
            "evidence": _safe_evidence_text(item.evidence, MAX_SELECTION_EVIDENCE_TEXT),
        } for item in selection.evidence_trace[:MAX_SELECTION_EVIDENCE_ITEMS]],
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
