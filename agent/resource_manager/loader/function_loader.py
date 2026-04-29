from typing import Any, Dict, List

from agent.resource_manager.loader.tag_utils import build_tags
from agent.resource_manager.models import FunctionRegistry


DEFAULT_RETURN_TYPE = {
    "data_type": "basic",
    "data_type_name": "void",
    "is_list": False,
}


def load_function_registry_from_json(payload: Dict[str, Any]) -> List[FunctionRegistry]:
    registry: List[FunctionRegistry] = []

    for class_payload in _iter_function_classes(payload):
        class_name = class_payload.get("class_name") or ""
        for function_payload in class_payload.get("func_list") or []:
            if not isinstance(function_payload, dict):
                continue
            registry.append(
                FunctionRegistry(
                    resource_id=f"func.{len(registry):04d}",
                    func_name=function_payload.get("func_name") or "",
                    func_desc=function_payload.get("func_desc") or "",
                    func_class=class_name,
                    param_list=function_payload.get("param_list") or [],
                    return_type=function_payload.get("return_type") or DEFAULT_RETURN_TYPE,
                    tag=_build_function_tags(function_payload, class_name),
                )
            )

    return registry


def load_function_registry_by_json(payload: Dict[str, Any]) -> Dict[str, FunctionRegistry]:
    return {
        function_registry.func_name: function_registry
        for function_registry in load_function_registry_from_json(payload)
    }


def _iter_function_classes(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    class_payloads: List[Dict[str, Any]] = []
    for key in ("func", "native_func"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                class_payloads.append(item)
    return class_payloads


def _build_function_tags(function_payload: Dict[str, Any], class_name: str) -> List[str]:
    values: List[str | None] = [
        function_payload.get("func_name"),
        function_payload.get("func_desc"),
        class_name,
    ]

    for param_payload in function_payload.get("param_list") or []:
        if not isinstance(param_payload, dict):
            continue
        values.extend(
            [
                param_payload.get("param_name"),
                param_payload.get("data_type_name"),
            ]
        )

    return_type = function_payload.get("return_type") or DEFAULT_RETURN_TYPE
    if isinstance(return_type, dict):
        values.append(return_type.get("data_type_name"))

    return build_tags(*values)
