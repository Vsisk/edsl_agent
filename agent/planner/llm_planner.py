import json
from typing import Any

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef
from agent.planner.models import PLAN_SCHEMA, Plan


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
            return Plan.model_validate(response)
        except (ValueError, ValidationError) as exc:
            invalid_plan_json = _dump_json(locals().get("response", {}))
            return self._repair(
                node_info=node_info,
                user_query=user_query,
                resources_json=resources_json,
                node_info_json=node_info_json,
                plan_schema_json=plan_schema_json,
                invalid_plan_json=invalid_plan_json,
                error_message=str(exc),
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
        return Plan.model_validate(response)


def _summarize_node(node_info: NodeDef) -> dict[str, Any]:
    return {
        "node_id": node_info.node_id,
        "node_path": node_info.node_path,
        "node_name": node_info.node_name,
        "description": node_info.description,
    }


def _summarize_filtered_environment(filtered_env: FilteredEnvironment) -> dict[str, Any]:
    return {
        "global_context": [_summarize_context(item) for item in filtered_env.selected_global_contexts],
        "local_context": [_summarize_context(item) for item in filtered_env.visible_local_context],
        "bo": [_summarize_bo(item) for item in filtered_env.selected_bos],
        "function": [_summarize_function(item) for item in filtered_env.selected_functions],
    }


def _summarize_context(resource: Any) -> dict[str, Any]:
    context_name = str(getattr(resource, "context_name", "") or "")
    return_type = getattr(resource, "return_type", None)
    return {
        "resource_id": getattr(resource, "resource_id", ""),
        "path": context_name,
        "name": context_name,
        "annotation": getattr(resource, "annotation", ""),
        "return_type": getattr(return_type, "data_type_name", None),
    }


def _summarize_bo(resource: Any) -> dict[str, Any]:
    return {
        "resource_id": getattr(resource, "resource_id", ""),
        "bo": getattr(resource, "bo_name", ""),
        "description": getattr(resource, "bo_desc", ""),
        "properties": [
            {
                "field_name": item.field_name,
                "description": item.description,
                "data_type_name": item.data_type_name,
            }
            for item in getattr(resource, "property_list", []) or []
        ],
        "naming_sql": [
            {
                "name": item.sql_name,
                "description": item.sql_description,
                "params": [
                    {
                        "name": param.param_name,
                        "data_type_name": param.data_type_name,
                    }
                    for param in item.param_list
                ],
            }
            for item in getattr(resource, "naming_sql_list", []) or []
        ],
    }


def _summarize_function(resource: Any) -> dict[str, Any]:
    return_type = getattr(resource, "return_type", None)
    return {
        "resource_id": getattr(resource, "resource_id", ""),
        "name": getattr(resource, "func_name", ""),
        "description": getattr(resource, "func_desc", ""),
        "class": getattr(resource, "func_class", ""),
        "params": [
            {
                "name": item.param_name,
                "data_type_name": item.data_type_name,
            }
            for item in getattr(resource, "param_list", []) or []
        ],
        "return_type": getattr(return_type, "data_type_name", None),
    }


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
