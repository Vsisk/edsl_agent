import json
from typing import Any

from agent.llm.generate_by_llm import generate_by_llm
from agent.llm.llm_client import LLMClient
from agent.models import NodeDef


RESOURCE_GROUPS = ("global_context", "local_context", "bo", "function")


class LLMResourceFilter:
    def __init__(
        self,
        client: LLMClient | None = None,
    ):
        self.client = client or LLMClient()

    @property
    def is_usable(self) -> bool:
        return self.client.is_usable

    def filter_resources(
        self,
        *,
        node_info: NodeDef,
        user_query: str,
        candidates: dict[str, list[Any]],
        limits: dict[str, int],
    ) -> dict[str, list[dict[str, str]]]:
        if not self.is_usable:
            return {}

        response = generate_by_llm(
            prompt_template="resource_filter",
            llm_name="base",
            lang="zh",
            client=self.client,
            user_requirement=user_query,
            node_info_json=_dump_json(_summarize_node(node_info)),
            limits_json=_dump_json(limits),
            candidates_json=_dump_json(_summarize_candidates(candidates)),
        )
        return _normalize_response(response)


def _summarize_node(node_info: NodeDef) -> dict[str, Any]:
    return {
        "node_id": node_info.node_id,
        "node_path": node_info.node_path,
        "node_name": node_info.node_name,
        "description": node_info.description,
    }


def _summarize_candidates(candidates: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        group: [_summarize_resource(resource, group) for resource in candidates.get(group, [])]
        for group in RESOURCE_GROUPS
    }


def _summarize_resource(resource: Any, group: str) -> dict[str, Any]:
    base = {
        "resource_id": getattr(resource, "resource_id", ""),
        "tags": list(getattr(resource, "tag", []) or []),
    }
    if group == "bo":
        base.update(
            {
                "name": getattr(resource, "bo_name", ""),
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
                        "sql_name": item.sql_name,
                        "sql_description": item.sql_description,
                        "params": [
                            {
                                "param_name": param.param_name,
                                "data_type_name": param.data_type_name,
                            }
                            for param in item.param_list
                        ],
                    }
                    for item in getattr(resource, "naming_sql_list", []) or []
                ],
            }
        )
    elif group == "function":
        return_type = getattr(resource, "return_type", None)
        base.update(
            {
                "name": getattr(resource, "func_name", ""),
                "description": getattr(resource, "func_desc", ""),
                "class": getattr(resource, "func_class", ""),
                "params": [
                    {
                        "param_name": item.param_name,
                        "data_type_name": item.data_type_name,
                    }
                    for item in getattr(resource, "param_list", []) or []
                ],
                "return_type": getattr(return_type, "data_type_name", None),
            }
        )
    else:
        return_type = getattr(resource, "return_type", None)
        base.update(
            {
                "name": getattr(resource, "context_name", ""),
                "annotation": getattr(resource, "annotation", ""),
                "property_type": getattr(resource, "property_type", ""),
                "return_type": getattr(return_type, "data_type_name", None) if return_type else None,
            }
        )
    return base


def _normalize_response(response: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    normalized: dict[str, list[dict[str, str]]] = {}
    for group in RESOURCE_GROUPS:
        items = response.get(group) or []
        if not isinstance(items, list):
            normalized[group] = []
            continue
        normalized_items: list[dict[str, str]] = []
        for item in items:
            normalized_item = _normalize_item(item)
            if normalized_item:
                normalized_items.append(normalized_item)
        normalized[group] = normalized_items
    return normalized


def _normalize_item(item: Any) -> dict[str, str]:
    if isinstance(item, str):
        return {"resource_id": item, "reason": ""}
    if not isinstance(item, dict):
        return {}
    resource_id = str(item.get("resource_id") or "").strip()
    if not resource_id:
        return {}
    return {
        "resource_id": resource_id,
        "reason": str(item.get("reason") or ""),
    }


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
