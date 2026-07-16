from typing import Any, Dict, List, Tuple

from jsonpath_ng import parse

from agent.resource_manager.loader.tag_utils import build_tags
from agent.resource_manager.models import LocalContextRegistry


PARENT_NODE_TYPES = {"parent", "parent_list"}
LOCAL_CONTEXT_FIELDS = (("local_context", "local"), ("lobal_context", "local"))


def load_visible_local_context_registry(edsl_tree: Dict[str, Any], node_path: str) -> List[LocalContextRegistry]:
    registry: List[LocalContextRegistry] = []
    normalized_path = _normalize_path(node_path)

    for ancestor_node, ancestor_path in _resolve_existing_path_nodes(edsl_tree, normalized_path):
        if not isinstance(ancestor_node, dict):
            continue
        if ancestor_node.get("tree_node_type") not in PARENT_NODE_TYPES:
            continue

        context_fields = LOCAL_CONTEXT_FIELDS
        if (
            ancestor_node.get("tree_node_type") == "parent_list"
            and _is_inside_list_body(normalized_path, ancestor_path)
        ):
            context_fields += (("iter_local_context", "iter"),)

        for field_name, property_type in context_fields:
            context_items = ancestor_node.get(field_name) or []
            if not isinstance(context_items, list):
                continue
            for index, context_item in enumerate(context_items):
                if not isinstance(context_item, dict):
                    continue
                property_name = str(context_item.get("property_name") or "").strip()
                if not property_name:
                    continue
                registry.append(
                    LocalContextRegistry(
                        resource_id=f"local.{len(registry):04d}",
                        context_name=f"$local$.{property_name}",
                        return_type=context_item.get("return_type"),
                        annotation=context_item.get("annotation") or "",
                        source_path=f"{ancestor_path}.{field_name}[{index}]",
                        property_type=property_type,
                        tag=_build_local_context_tags(property_name, context_item, ancestor_node),
                    )
                )

    return registry


def _normalize_path(node_path: str) -> str:
    path = node_path.strip()
    if not path.startswith("$"):
        path = f"$.{path.lstrip('.')}"
    return path


def _is_inside_list_body(node_path: str, list_path: str) -> bool:
    body_path = f"{list_path}.children"
    return node_path == body_path or node_path.startswith(
        (f"{body_path}[", f"{body_path}.")
    )


def _resolve_existing_path_nodes(edsl_tree: Dict[str, Any], node_path: str) -> List[Tuple[Any, str]]:
    resolved_nodes: List[Tuple[Any, str]] = []

    for candidate_path in _iter_candidate_paths(node_path):
        matches = parse(candidate_path).find(edsl_tree)
        if not matches:
            continue
        resolved_nodes.append((matches[0].value, candidate_path))

    return resolved_nodes


def _iter_candidate_paths(node_path: str) -> List[str]:
    path = _normalize_path(node_path)

    paths: List[str] = []
    while path and path != "$":
        paths.append(path)
        path = _parent_path(path)
    return list(reversed(paths))


def _parent_path(path: str) -> str:
    if path.endswith("]"):
        bracket_index = path.rfind("[")
        return path[:bracket_index]
    dot_index = path.rfind(".")
    return path[:dot_index] if dot_index > 0 else "$"


def _get_node_xml_name(node: Dict[str, Any]) -> str:
    xml_name_property = node.get("xml_name_property") or {}
    if not isinstance(xml_name_property, dict):
        return ""
    return str(xml_name_property.get("xml_name") or "").strip()


def _build_local_context_tags(property_name: str, context_item: Dict[str, Any], node: Dict[str, Any]) -> List[str]:
    tags = [property_name]
    return_type = context_item.get("return_type") or {}
    return_type_name = return_type.get("data_type_name") if isinstance(return_type, dict) else None
    for tag in build_tags(
        _get_node_xml_name(node),
        node.get("annotation"),
        context_item.get("annotation"),
        return_type_name,
    ):
        if tag and tag not in tags:
            tags.append(tag)
    return tags
