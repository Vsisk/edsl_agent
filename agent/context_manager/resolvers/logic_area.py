from __future__ import annotations

from typing import Any

from agent.context_manager.models import BuildContextRequest, ContextAsset, ContextEvidenceItem, LogicAreaContextBlock, NodeContextBlock


class LogicAreaContextResolver:
    def __init__(self, retriever: Any = None, reranker: Any = None) -> None:
        self.retriever, self.reranker = retriever, reranker

    def resolve(self, request: BuildContextRequest, loaded_resource: Any, node_block: NodeContextBlock) -> LogicAreaContextBlock | None:
        records = _logic_areas(loaded_resource.edsl_tree)
        if not records: return None
        assets = [_asset(item, request) for item in records if _area_id(item)]
        requested = _strings(node_block.current_node.get("reference_logic_area_id_list")) or _strings(request.target_logic_area_id_list)
        evidence: list[ContextEvidenceItem] = []
        if requested:
            selected = [asset for asset in assets if asset.logic_area_id in requested]
            action = "logic_area_id_match"
        elif self.retriever is not None and self.reranker is not None:
            recalled = self.retriever.retrieve(request.query, assets, semantic_limit=max(request.top_k, 10))
            result = self.reranker.rerank(request.query, recalled, {"node": node_block.model_dump(mode="json")})
            selected = list(result.selected_assets)
            evidence.extend(getattr(result, "evidence_trace", []) or [])
            action = "logic_area_semantic_match"
        else:
            selected, action = [], "logic_area_unselected"
        ids = [asset.logic_area_id for asset in selected if asset.logic_area_id]
        for asset in selected:
            evidence.append(ContextEvidenceItem(source="edsl_project", action=action, asset_id=asset.asset_id, evidence=f"Selected logic area {asset.logic_area_id}"))
        source_records = [asset.content for asset in selected]
        sa, se, cbs, fees, columns, samples = [], [], [], [], [], []
        for record in source_records:
            _semi_text(record.get("edsl_semi_struct"), sa, se)
            cbs_value = record.get("cbs_terms") or record.get("cbs_term_list") or record.get("cbs_field_list")
            cbs.extend(item for item in _term_texts(cbs_value) if item not in cbs)
            fee = {key: record[key] for key in ("requirement_fee_category", "leaf_columns", "summary_info") if key in record}
            if fee: fees.append(fee)
            _extend_unique(columns, record.get("columns") or record.get("column_list"))
            _extend_unique(samples, record.get("samples") or record.get("sample_list"))
        return LogicAreaContextBlock(logic_area_ids=ids, assets=selected, evidence=evidence, sa_texts=sa, se_texts=se, cbs_terms=cbs, fee_category_summaries=fees, columns=columns, samples=samples)


def _logic_areas(tree: Any) -> list[dict]:
    if isinstance(tree, dict):
        for key in ("logic_area_list", "logic_areas"):
            value = tree.get(key)
            if isinstance(value, list): return [item for item in value if isinstance(item, dict)]
        children = tree.values()
    elif isinstance(tree, list):
        children = tree
    else:
        return []
    for value in children:
        found = _logic_areas(value)
        if found: return found
    return []


def _area_id(record: dict) -> str:
    return str(record.get("id") or record.get("logic_area_id") or record.get("area_id") or "").strip()


def _asset(record: dict, request: BuildContextRequest) -> ContextAsset:
    area_id = _area_id(record)
    parts = [record.get(key) for key in ("name", "description", "type", "cbs_area_type") if record.get(key)]
    return ContextAsset(asset_id=f"logic_area:{area_id}", asset_type="logic_area", scope="logic_area", site_id=request.site_id, project_id=request.project_id, logic_area_id=area_id, content=record, index_text="; ".join(map(str, parts)), source="edsl_project")


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _semi_text(value: Any, sa: list[str], se: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            target = sa if normalized in {"sa", "sa_text", "sa_texts"} else se if normalized in {"se", "se_text", "se_texts"} else None
            if target is not None:
                for text in _term_texts(child):
                    if text not in target: target.append(text)
            else: _semi_text(child, sa, se)
    elif isinstance(value, list):
        for child in value: _semi_text(child, sa, se)


def _term_texts(value: Any) -> list[str]:
    if value is None: return []
    if isinstance(value, (str, int, float)): return [str(value)]
    if isinstance(value, list): return [text for item in value for text in _term_texts(item)]
    if isinstance(value, dict):
        preferred = [value[key] for key in ("text", "name", "term", "value", "description") if key in value]
        return [text for item in (preferred or list(value.values())) for text in _term_texts(item)]
    return []


def _extend_unique(target: list, value: Any) -> None:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    for item in items:
        if item not in target: target.append(item)
