from typing import Any, Dict, Iterable, List, Optional

from agent.resource_manager.loader.tag_utils import build_tags
from agent.resource_manager.models import ContextRegistry


EXPANDABLE_DATA_TYPES = {"bo", "logic", "extattr"}
CONTEXT_ROOT_KEYS = ("global_context", "sub_global_context")


def load_context_registry_from_json(payload: Dict[str, Any]) -> List[ContextRegistry]:
    registry: List[ContextRegistry] = []

    for root_key in CONTEXT_ROOT_KEYS:
        root_node = payload.get(root_key)
        for node in _iter_nodes(root_node):
            _collect_context_registry(
                node=node,
                registry=registry,
                name_parts=[],
                annotation_parts=[],
                tag_parts=[],
                inherited_property_type=None,
            )

    return registry


def load_context_registry_by_json(payload: Dict[str, Any]) -> Dict[str, ContextRegistry]:
    return {
        context_registry.context_name: context_registry
        for context_registry in load_context_registry_from_json(payload)
    }


def _collect_context_registry(
    node: Dict[str, Any],
    registry: List[ContextRegistry],
    name_parts: List[str],
    annotation_parts: List[str],
    tag_parts: List[str],
    inherited_property_type: Optional[str],
) -> None:
    property_name = str(node.get("property_name") or "").strip()
    current_name_parts = name_parts + ([property_name] if property_name else [])

    annotation = str(node.get("annotation") or "").strip()
    current_annotation_parts = annotation_parts + ([annotation] if annotation else [])

    property_type = node.get("property_type") or inherited_property_type
    return_type = node.get("return_type") or {}
    data_type = str(return_type.get("data_type") or "").strip()
    children = _get_children(node)

    current_tag_parts = [*tag_parts]
    if property_name and property_name != "$ctx$":
        current_tag_parts.append(property_name)
    data_type_name = return_type.get("data_type_name")
    if data_type_name:
        current_tag_parts.append(str(data_type_name))

    if return_type and (not _is_expandable(data_type) or not children):
        tag_parts_for_leaf = [property_name, property_type, annotation, *tag_parts]
        if data_type_name:
            tag_parts_for_leaf.append(str(data_type_name))
        registry.append(
            ContextRegistry(
                resource_id=f"ctx.{len(registry):04d}",
                context_name=".".join(current_name_parts),
                return_type=return_type,
                property_type=property_type or "custom",
                annotation=".".join(current_annotation_parts),
                tag=build_tags(*[str(tag) for tag in tag_parts_for_leaf if tag]),
            )
        )
        return

    for child in children:
        _collect_context_registry(
            node=child,
            registry=registry,
            name_parts=current_name_parts,
            annotation_parts=current_annotation_parts,
            tag_parts=current_tag_parts,
            inherited_property_type=property_type,
        )


def _iter_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _get_children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    children = node.get("children")
    if children is None:
        children = node.get("sub_properties")

    if isinstance(children, dict):
        return list(_iter_nodes(children))
    if isinstance(children, list):
        return [child for child in children if isinstance(child, dict)]
    return []


def _is_expandable(data_type: str) -> bool:
    return data_type.lower() in EXPANDABLE_DATA_TYPES


def _dedupe(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
