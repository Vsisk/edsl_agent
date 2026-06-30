from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


CREATE_PARENT_TYPES = {
    "parent",
    "parent_list",
    "ab_single_mapping_table",
    "ab_two_level_table",
    "ab_pivot_table",
}

_IDENTIFIER_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AB_FIELD_SLOTS = {
    "detail_fields",
    "group_by_fields",
    "group_related_fields",
    "sum_fields",
    "summary_fields",
}


class NodeLocateCandidate(BaseModel):
    node_id: str
    jsonpath: str
    tree_node_type: str
    xml_name: str | None = None
    annotation: str | None = None
    parent_xml_name: str | None = None
    parent_node_id: str | None = None
    child_count: int = 0
    identity_field: str | None = None
    field_slot: str | None = None


def _property_path(path: str, key: str) -> str:
    if _IDENTIFIER_KEY.fullmatch(key):
        return f"{path}.{key}"
    escaped_key = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{path}['{escaped_key}']"


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def build_node_index(target_tree: dict[str, Any]) -> dict[str, NodeLocateCandidate]:
    """Build a depth-first index of operation target nodes."""
    index: dict[str, NodeLocateCandidate] = {}

    def visit(
        value: Any,
        path: str,
        parent: NodeLocateCandidate | None,
        ab_parent: NodeLocateCandidate | None = None,
        field_slot: str | None = None,
    ) -> None:
        if isinstance(value, dict):
            node_id = value.get("node_id")
            tree_node_type = value.get("tree_node_type")
            current_parent = parent

            if (
                isinstance(node_id, str)
                and bool(node_id)
                and isinstance(tree_node_type, str)
                and bool(tree_node_type)
            ):
                if node_id in index:
                    raise ValueError(f"duplicate node_id: {node_id}")

                xml_name_property = value.get("xml_name_property")
                xml_name = (
                    _optional_string(xml_name_property.get("xml_name"))
                    if isinstance(xml_name_property, dict)
                    else None
                )
                children = value.get("children")
                candidate = NodeLocateCandidate(
                    node_id=node_id,
                    jsonpath=path,
                    tree_node_type=tree_node_type,
                    xml_name=xml_name,
                    annotation=_optional_string(value.get("annotation")),
                    parent_xml_name=parent.xml_name if parent is not None else None,
                    parent_node_id=parent.node_id if parent is not None else None,
                    child_count=len(children) if isinstance(children, list) else 0,
                    identity_field="node_id",
                )
                index[node_id] = candidate
                current_parent = candidate
                if tree_node_type.startswith("ab_"):
                    ab_parent = candidate

            field_id = value.get("field_id")
            if field_slot is not None and isinstance(field_id, str) and bool(field_id.strip()):
                if field_id in index:
                    raise ValueError(f"duplicate node_id or field_id: {field_id}")
                xml_name_property = value.get("xml_name_property")
                candidate = NodeLocateCandidate(
                    node_id=field_id,
                    jsonpath=path,
                    tree_node_type="ab_summary_field" if field_slot == "summary_fields" else "ab_field",
                    xml_name=(
                        _optional_string(xml_name_property.get("xml_name"))
                        if isinstance(xml_name_property, dict)
                        else None
                    ),
                    annotation=_optional_string(value.get("annotation")),
                    parent_xml_name=ab_parent.xml_name if ab_parent is not None else None,
                    parent_node_id=ab_parent.node_id if ab_parent is not None else None,
                    identity_field="field_id",
                    field_slot=field_slot,
                )
                index[field_id] = candidate

            for key, child in value.items():
                child_slot = str(key) if ab_parent is not None and str(key) in _AB_FIELD_SLOTS else field_slot
                visit(child, _property_path(path, str(key)), current_parent, ab_parent, child_slot)
            return

        if isinstance(value, list):
            for item_index, child in enumerate(value):
                visit(child, f"{path}[{item_index}]", parent, ab_parent, field_slot)

    visit(target_tree, "$", None)
    return index


def is_valid_candidate(intent_type: str, candidate: NodeLocateCandidate) -> bool:
    if intent_type == "create_node":
        return candidate.tree_node_type in CREATE_PARENT_TYPES
    if intent_type == "generate_expression":
        return candidate.tree_node_type in {"simple_leaf", "ab_field"}
    if intent_type == "modify_node":
        return candidate.identity_field == "node_id"
    if intent_type == "delete_node":
        return True
    return False
