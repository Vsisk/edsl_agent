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
        data_source = _current_data_source(current)
        bo_name, naming_sql_ids = _data_source_references(data_source)
        asset = ContextAsset(asset_id=f"edsl_node:{current.get('node_id', request.json_path)}", asset_type="edsl_node", scope="node", site_id=request.site_id, project_id=request.project_id, json_path=request.json_path, content=current, index_text=_node_text(current), source="edsl_project")
        evidence = [ContextEvidenceItem(source="edsl_project", action="node_resolved", asset_id=asset.asset_id, evidence=f"Exact JSONPath {request.json_path}")]
        return NodeContextBlock(
            json_path=request.json_path, node=current, assets=[asset], evidence=evidence,
            current_node=current, parent_node=parent, ancestors=ancestors,
            sibling_summaries=[_summary(item) for item in siblings],
            visible_local_context=local, visible_iter_context=iteration,
            existing_data_source_ids=_collect_scalar_values(tree, {"data_source_id"}),
            existing_data_source=data_source,
            existing_bo_name=bo_name,
            existing_bo_ids=[bo_name] if bo_name else [],
            existing_naming_sql_ids=naming_sql_ids,
            is_simple_leaf=current.get("tree_node_type") == "simple_leaf",
            simple_leaf_summary=_simple_leaf_summary(current),
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
    node_type = node.get("tree_node_type")
    group_region = content.get("group_region") if isinstance(content.get("group_region"), dict) else None
    detail_region = content.get("detail_region") if isinstance(content.get("detail_region"), dict) else None
    detail_fields = list(content.get("detail_fields") or [])
    if detail_region: detail_fields.extend(detail_region.get("detail_fields") or [])
    summary_fields = list(content.get("summary_fields") or [])
    if node_type == "ab_pivot_table" and group_region:
        summary_fields.extend(group_region.get("sum_fields") or [])
    elif node_type == "ab_two_level_table" and group_region:
        summary_fields.extend(group_region.get("summary_fields") or [])
    return {
        "data_source": content.get("data_source"),
        "detail_fields": _dedupe(detail_fields),
        "group_by_fields": list(content.get("group_by_fields") or []),
        "detail_region": detail_region,
        "group_region": group_region,
        "summary_fields": _dedupe(summary_fields),
    }


def _collect_scalar_values(value: Any, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, (str, int)) and str(child) not in found: found.append(str(child))
            found.extend(item for item in _collect_scalar_values(child, keys) if item not in found)
    elif isinstance(value, list):
        for child in value: found.extend(item for item in _collect_scalar_values(child, keys) if item not in found)
    return found


def _simple_leaf_summary(node: dict) -> dict | None:
    if node.get("tree_node_type") != "simple_leaf": return None
    fields = ("xml_name_property", "annotation", "edsl_semi_struct", "data_type_config", "data_expression", "data_expresssion", "reference_logic_area_id_list")
    return {key: node[key] for key in fields if key in node}


def _current_data_source(node: dict) -> dict | None:
    content = node.get("ab_content") if isinstance(node.get("ab_content"), dict) else node
    value = content.get("data_source")
    if isinstance(value, dict): return value
    value = content.get("ab_data_source")
    return value if isinstance(value, dict) else None


def _data_source_references(data_source: dict | None) -> tuple[str | None, list[str]]:
    if not data_source: return None, []
    query = data_source.get("sql_query") if isinstance(data_source.get("sql_query"), dict) else {}
    bo_name = query.get("bo_name") or data_source.get("bo_name")
    ids = _collect_scalar_values(query, {"naming_sql_id", "naming_sql", "naming_sql_name"})
    return (str(bo_name) if bo_name not in (None, "") else None), _dedupe(ids)


def _dedupe(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value not in result: result.append(value)
    return result
