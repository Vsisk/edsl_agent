from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.models import PLAN_SCHEMA, Plan
from agent.naming_sql_selector.plan_validator import validate_naming_sql_plan

if TYPE_CHECKING:
    from agent.naming_sql_selector.models import NamingSqlSelectionResult

MAX_SUMMARY_TEXT = 512
MAX_SUMMARY_ITEMS = 100
MAX_INVALID_PLAN_EXCERPT = 12_000
MAX_ERROR_EXCERPT = 2_000


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
    ) -> Plan:
        if not self.is_usable:
            raise RuntimeError("LLM planner is not usable")

        resources_json = _dump_json(_summarize_filtered_environment(filtered_env))
        node_info_json = _dump_json(_summarize_node(node_info))
        plan_schema_json = _dump_json(PLAN_SCHEMA)

        try:
            response = generate_by_llm(
                prompt_template="planner",
                llm_name="base",
                lang="zh",
                client=self.client,
                user_requirement=user_query,
                node_info_json=node_info_json,
                resources_json=resources_json,
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
        node_info_json: str,
        plan_schema_json: str,
        invalid_plan_json: str,
        error_message: str,
        naming_sql_selection: NamingSqlSelectionResult | None,
    ) -> Plan:
        response = generate_by_llm(
            prompt_template="planner_repair",
            llm_name="base",
            lang="zh",
            client=self.client,
            user_requirement=user_query,
            node_info_json=node_info_json,
            resources_json=resources_json,
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
    summary = {
        "global_context": [
            _summarize_context(item)
            for item in filtered_env.selected_global_contexts[:MAX_SUMMARY_ITEMS]
        ],
        "local_context": [
            _summarize_context(item)
            for item in filtered_env.visible_local_context[:MAX_SUMMARY_ITEMS]
        ],
        "bo": [
            _summarize_bo(item)
            for item in filtered_env.selected_bos[:MAX_SUMMARY_ITEMS]
        ],
        "function": [
            _summarize_function(item)
            for item in filtered_env.selected_functions[:MAX_SUMMARY_ITEMS]
        ],
    }
    selection = filtered_env.naming_sql_selection
    if selection is not None and selection.selected is not None:
        chosen = selection.selected
        summary["naming_sql_selection"] = {
            "bo": selection.selected_bo,
            "name": chosen.sql_name,
            "bindings": [
                {
                    "name": item.param_name,
                    "source_ref": item.source_ref,
                }
                for item in chosen.binding_plan.bindings
            ],
        }
        for bo in summary["bo"]:
            bo.pop("naming_sql", None)
    return summary


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
