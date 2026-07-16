from typing import Any, Dict, List, Tuple

from jsonpath_ng import parse

from agent.resource_manager.loader.tag_utils import build_tags
from agent.resource_manager.models import LocalContextRegistry


PARENT_NODE_TYPES = {"parent", "parent_list"}
LOCAL_CONTEXT_FIELDS = (("local_context", "local"), ("lobal_context", "local"))
DEFAULT_LOCAL_CONTEXT_RETURN_TYPE = {
    "data_type": "basic",
    "data_type_name": "String",
    "is_list": False,
}


def load_visible_local_context_registry(edsl_tree: Dict[str, Any], node_path: str) -> List[LocalContextRegistry]:
    registry: List[LocalContextRegistry] = []
    normalized_path = _normalize_path(node_path)
    nearest_list: Tuple[Dict[str, Any], str] | None = None

    for ancestor_node, ancestor_path in _resolve_existing_path_nodes(edsl_tree, normalized_path):
        if not isinstance(ancestor_node, dict):
            continue
        node_type = ancestor_node.get("tree_node_type")
        if node_type not in PARENT_NODE_TYPES:
            continue

        context_fields = LOCAL_CONTEXT_FIELDS
        if (
            node_type == "parent_list"
            and _is_inside_list_body(normalized_path, ancestor_path)
        ):
            nearest_list = (ancestor_node, ancestor_path)
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
                return_type = _local_context_return_type(context_item)
                registry.append(
                    LocalContextRegistry(
                        resource_id=f"local.{len(registry):04d}",
                        context_name=f"$local$.{property_name}",
                        return_type=return_type,
                        annotation=context_item.get("annotation") or "",
                        source_path=f"{ancestor_path}.{field_name}[{index}]",
                        property_type=property_type,
                        tag=_build_local_context_tags(
                            property_name,
                            context_item,
                            ancestor_node,
                            return_type,
                        ),
                    )
                )

    if nearest_list is not None:
        list_node, list_path = nearest_list
        return_type = _list_element_return_type(list_node)
        if return_type is not None:
            context_item = {
                "annotation": list_node.get("annotation") or "",
                "return_type": return_type,
            }
            registry.append(
                LocalContextRegistry(
                    resource_id=f"local.{len(registry):04d}",
                    context_name="$iter$",
                    return_type=return_type,
                    annotation=context_item["annotation"],
                    source_path=f"{list_path}.data_source",
                    property_type="iter",
                    tag=_build_local_context_tags(
                        "$iter$",
                        context_item,
                        list_node,
                        return_type,
                    ),
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


def _list_element_return_type(node: Dict[str, Any]) -> Dict[str, Any] | None:
    return_type = _data_source_return_type(node.get("data_source"))
    if return_type is None:
        return None
    return {**return_type, "is_list": False}


def _data_source_return_type(data_source: Any) -> Dict[str, Any] | None:
    if not isinstance(data_source, dict):
        return None

    source_type = str(data_source.get("data_source_type") or "").strip().lower()
    if source_type == "sql":
        sql_query = data_source.get("sql_query")
        if not isinstance(sql_query, dict):
            return None
        bo_name = str(sql_query.get("bo_name") or "").strip()
        if not bo_name:
            return None
        return {
            "data_type": "bo",
            "data_type_name": bo_name,
            "is_list": True,
        }

    if source_type == "expression":
        data_expression = data_source.get("data_expression")
        return_type = (
            data_expression.get("return_type")
            if isinstance(data_expression, dict)
            else None
        )
        if not isinstance(return_type, dict):
            return None
        data_type = str(return_type.get("data_type") or "").strip()
        if not data_type:
            return None
        return {
            "data_type": data_type,
            "data_type_name": return_type.get("data_type_name"),
            "is_list": bool(return_type.get("is_list", False)),
        }

    return None


def _local_context_return_type(context_item: Dict[str, Any]) -> Dict[str, Any]:
    return_type = _data_source_return_type(context_item.get("data_source"))
    if return_type is None:
        return dict(DEFAULT_LOCAL_CONTEXT_RETURN_TYPE)

    data_type_name = str(return_type.get("data_type_name") or "").strip()
    if not data_type_name:
        return dict(DEFAULT_LOCAL_CONTEXT_RETURN_TYPE)
    return {**return_type, "data_type_name": data_type_name}


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


def _build_local_context_tags(
    property_name: str,
    context_item: Dict[str, Any],
    node: Dict[str, Any],
    return_type: Dict[str, Any],
) -> List[str]:
    tags = [property_name]
    return_type_name = return_type.get("data_type_name")
    for tag in build_tags(
        _get_node_xml_name(node),
        node.get("annotation"),
        context_item.get("annotation"),
        return_type_name,
    ):
        if tag and tag not in tags:
            tags.append(tag)
    return tags
