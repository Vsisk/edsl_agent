from __future__ import annotations

from typing import Any

from jsonpath_ng import parse

from agent.context_manager.errors import ContextBuildError, EDSL_NODE_NOT_FOUND
from agent.context_manager.models import BuildContextRequest, ContextAsset, ContextEvidenceItem, NodeContextBlock
from agent.resource_manager.loader.local_context_loader import load_visible_local_context_registry


FEE_TABLE_TYPES = {"ab_pivot_table", "ab_two_level_table", "ab_single_mapping_table"}


class EdslProjectContextResolver:
    def resolve(self, request: BuildContextRequest, loaded_resource: Any) -> NodeContextBlock:
        tree = loaded_resource.edsl_tree
        try:
            matches = parse(request.json_path).find(tree)
        except Exception as exc:
            raise ContextBuildError(EDSL_NODE_NOT_FOUND, request.json_path) from exc
        if len(matches) != 1 or not isinstance(matches[0].value, dict):
            raise ContextBuildError(EDSL_NODE_NOT_FOUND, request.json_path)
        current = matches[0].value
        ancestors = _node_ancestors(tree, current)
        parent = ancestors[-1] if ancestors else None
        siblings = _siblings(parent, current)
        visible = load_visible_local_context_registry(tree, request.json_path)
        local = [item.model_dump(mode="json") for item in visible if str(item.property_type.value if hasattr(item.property_type, "value") else item.property_type) == "local"]
        iteration = [item.model_dump(mode="json") for item in visible if str(item.property_type.value if hasattr(item.property_type, "value") else item.property_type) == "iter"]
        fee = _fee_summary(current)
        asset = ContextAsset(asset_id=f"edsl_node:{current.get('node_id', request.json_path)}", asset_type="edsl_node", scope="node", site_id=request.site_id, project_id=request.project_id, json_path=request.json_path, content=current, index_text=_node_text(current), source="edsl_project")
        evidence = [ContextEvidenceItem(source="edsl_project", action="node_resolved", asset_id=asset.asset_id, evidence=f"Exact JSONPath {request.json_path}")]
        return NodeContextBlock(
            json_path=request.json_path, node=current, assets=[asset], evidence=evidence,
            current_node=current, parent_node=parent, ancestors=ancestors,
            sibling_summaries=[_summary(item) for item in siblings],
            visible_local_context=local, visible_iter_context=iteration,
            existing_data_source_ids=_collect_values(tree, {"data_source", "data_source_id"}),
            existing_bo_ids=sorted(str(key) for key in getattr(loaded_resource, "bo_registry", {})),
            existing_naming_sql_ids=_naming_sql_ids(getattr(loaded_resource, "bo_registry", {})),
            is_simple_leaf=current.get("tree_node_type") not in {"parent", "parent_list"},
            fee_table_summary=fee,
        )


def _node_ancestors(root: Any, target: dict) -> list[dict]:
    def walk(value: Any, chain: list[dict]) -> list[dict] | None:
        if value is target:
            return chain
        if isinstance(value, dict):
            next_chain = chain + [value] if value.get("node_id") is not None else chain
            for child in value.values():
                found = walk(child, next_chain)
                if found is not None: return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, chain)
                if found is not None: return found
        return None
    return walk(root, []) or []


def _siblings(parent: dict | None, current: dict) -> list[dict]:
    if not parent: return []
    for value in parent.values():
        if isinstance(value, list) and any(item is current for item in value):
            return [item for item in value if isinstance(item, dict) and item is not current]
    return []


def _summary(node: dict) -> dict:
    keys = ("node_id", "tree_node_type", "annotation", "name", "xml_name_property")
    return {key: node[key] for key in keys if key in node}


def _node_text(node: dict) -> str:
    return "; ".join(str(node.get(key)) for key in ("node_id", "tree_node_type", "annotation", "name") if node.get(key))


def _fee_summary(node: dict) -> dict | None:
    if node.get("tree_node_type") not in FEE_TABLE_TYPES: return None
    content = node.get("ab_content") if isinstance(node.get("ab_content"), dict) else node
    fields = ("data_source", "detail_fields", "group_by_fields", "group_region", "detail_region", "summary_fields")
    return {key: content.get(key) for key in fields if key in content}


def _collect_values(value: Any, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, (str, int)) and str(child) not in found: found.append(str(child))
            found.extend(item for item in _collect_values(child, keys) if item not in found)
    elif isinstance(value, list):
        for child in value: found.extend(item for item in _collect_values(child, keys) if item not in found)
    return found


def _naming_sql_ids(registries: Any) -> list[str]:
    result = []
    for registry in getattr(registries, "values", lambda: [])():
        for item in getattr(registry, "naming_sql_list", []) or []:
            value = getattr(item, "naming_sql_id", None)
            if value and str(value) not in result: result.append(str(value))
    return result
