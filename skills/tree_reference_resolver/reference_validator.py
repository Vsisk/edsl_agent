from __future__ import annotations

import re
from typing import Any

from .models import NodeIndexEntry, ReferenceSearchSpec, TreeReferenceCandidate, TreeReferenceResolveInput


_PART_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def resolve_json_path(tree: dict[str, Any], path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError("json path must start with $")
    current: Any = tree
    for name, index in _PART_RE.findall(path[1:]):
        current = current[int(index)] if index else current[name]
    return current


class ReferenceValidator:
    def validate(
        self,
        selected: TreeReferenceCandidate,
        request: TreeReferenceResolveInput,
        spec: ReferenceSearchSpec,
        node_index: list[NodeIndexEntry],
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []
        entry = next((item for item in node_index if item.node_id == selected.node_id and item.json_path == selected.json_path), None)
        if entry is None:
            return False, ["selected node_id/json_path does not exist in the node index"]
        try:
            raw_node = resolve_json_path(request.tree_json, selected.json_path)
            if not isinstance(raw_node, dict):
                errors.append("selected json_path does not resolve to a node")
        except (KeyError, IndexError, TypeError, ValueError):
            return False, ["selected json_path cannot be located in tree_json"]

        target_id = request.target_node.get("node_id") or request.target_node.get("id")
        target_path = request.target_node_path
        if target_id is not None and str(target_id) == selected.node_id:
            errors.append("selected node is the target node itself")
        if target_path and selected.json_path == target_path:
            errors.append("selected node is the target node itself")
        if target_path and selected.json_path.startswith(f"{target_path}.children["):
            errors.append("selected node is a descendant of the target node")
        expected = request.expected_node_types or spec.expected_node_types
        if expected and selected.tree_node_type not in expected:
            errors.append(f"node type {selected.tree_node_type} is not one of {expected}")
        expected_lower = {item.lower() for item in spec.expected_node_types}
        if "parent_list" in expected_lower:
            has_structure = bool(raw_node.get("children") or raw_node.get("iter_local_context") or raw_node.get("data_source"))
            if selected.tree_node_type != "parent_list" or not has_structure:
                errors.append("parent_list candidate lacks required list structure")
        if any(item == "ab" or item.startswith("ab_") for item in expected_lower) and not isinstance(raw_node.get("ab_content"), dict):
            errors.append("AB candidate lacks ab_content")
        if "simple_leaf" in expected_lower:
            if selected.tree_node_type != "simple_leaf" or not (raw_node.get("data_expression") is not None or raw_node.get("data_type_config") is not None):
                errors.append("simple_leaf candidate lacks value configuration")
        return not errors, errors
