from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent.context_manager.errors import ContextBuildError, EDSL_NODE_NOT_FOUND, RULE_FILE_MISSING
from agent.context_manager.models import BuildContextRequest
from agent.context_manager.resolvers import EdslProjectContextResolver, GlobalContextResolver, LogicAreaContextResolver


def request(path="$.nodes[0].children[0].children[1]", ids=None):
    return BuildContextRequest(site_id="s", project_id="p", query="charge fee", node={"node_id": "lie"}, json_path=path, target_logic_area_id_list=ids or [])


@pytest.fixture
def tree():
    return {
        "logic_area_list": [
            {"id": "la.node", "name": "Charge", "description": "charge area", "type": "fee", "cbs_area_type": "usage", "edsl_semi_struct": {"sa": "current charge", "nested": [{"se": "charge event"}]}, "cbs_terms": ["charge", {"name": "amount"}], "requirement_fee_category": [{"name": "usage fee"}], "leaf_columns": [{"name": "amount"}], "summary_info": {"label": "total"}, "columns": ["account", "amount"], "samples": [{"amount": 12}]},
            {"id": "la.request", "name": "Other"},
            {"id": "la.semantic", "name": "Semantic charge", "description": "fallback"},
        ],
        "nodes": [{"node_id": "root", "tree_node_type": "parent", "children": [
            {"node_id": "parent", "tree_node_type": "parent", "local_context": [{"property_name": "accountId", "annotation": "account"}], "iter_local_context": [{"property_name": "line", "annotation": "line"}], "children": [
                {"node_id": "sibling", "tree_node_type": "field", "annotation": "neighbor"},
                {"node_id": "target", "tree_node_type": "ab_pivot_table", "reference_logic_area_id_list": ["la.node"], "ab_content": {"data_source": "charges", "detail_fields": ["detail"], "group_by_fields": ["category"], "group_region": {"group_related_fields": ["region"]}, "detail_region": {"detail_fields": ["item"]}, "summary_fields": ["total"]}},
            ]},
        ]}],
    }


def test_global_rules_required_and_traced(tmp_path):
    (tmp_path / "chains").mkdir()
    (tmp_path / "GLOBAL.md").write_text("global rule", encoding="utf-8")
    (tmp_path / "chains" / "namingsql_selection.md").write_text("chain rule", encoding="utf-8")
    block = GlobalContextResolver(tmp_path).resolve(request())
    assert [a.asset_type for a in block.assets] == ["global_rule", "chain_rule"]
    assert block.loaded_paths == [str(tmp_path / "GLOBAL.md"), str(tmp_path / "chains" / "namingsql_selection.md")]
    assert len(block.evidence) == 2


@pytest.mark.parametrize("empty", [False, True])
def test_global_rule_missing_or_empty_fails(tmp_path, empty):
    if empty:
        (tmp_path / "GLOBAL.md").write_text("", encoding="utf-8")
    with pytest.raises(ContextBuildError) as exc:
        GlobalContextResolver(tmp_path).resolve(request())
    assert exc.value.code == RULE_FILE_MISSING


def test_project_resolver_extracts_structure_visibility_and_fee_table(tree):
    before = deepcopy(tree)
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={"ChargeBO": object()}, context_registry={"$ctx$.account": object()})
    block = EdslProjectContextResolver().resolve(request(), loaded)
    assert block.current_node["node_id"] == "target"
    assert block.parent_node["node_id"] == "parent"
    assert [n["node_id"] for n in block.ancestors] == ["root", "parent"]
    assert [n["node_id"] for n in block.sibling_summaries] == ["sibling"]
    assert block.visible_local_context[0]["context_name"] == "$local$.accountId"
    assert block.visible_iter_context[0]["context_name"] == "$iter$.line"
    assert block.fee_table_summary["group_by_fields"] == ["category"]
    assert block.fee_table_summary["group_region"] == {"group_related_fields": ["region"]}
    assert block.existing_bo_ids == ["ChargeBO"]
    assert tree == before


@pytest.mark.parametrize("path", ["$.missing[0]", "$.[bad"])
def test_project_resolver_maps_missing_and_invalid_path(path, tree):
    with pytest.raises(ContextBuildError) as exc:
        EdslProjectContextResolver().resolve(request(path), SimpleNamespace(edsl_tree=tree, bo_registry={}, context_registry={}))
    assert exc.value.code == EDSL_NODE_NOT_FOUND


def test_logic_area_node_ids_win_and_content_is_extracted(tree):
    loaded = SimpleNamespace(edsl_tree=tree)
    node = EdslProjectContextResolver().resolve(request(ids=["la.request"]), loaded)
    block = LogicAreaContextResolver().resolve(request(ids=["la.request"]), loaded, node)
    assert block.logic_area_ids == ["la.node"]
    assert block.sa_texts == ["current charge"]
    assert block.se_texts == ["charge event"]
    assert "amount" in block.cbs_terms
    assert block.fee_category_summaries[0]["summary_info"] == {"label": "total"}
    assert block.columns == ["account", "amount"]
    assert block.samples == [{"amount": 12}]


def test_logic_area_semantic_fallback_uses_injected_services(tree):
    class Retriever:
        def __init__(self): self.called = False
        def retrieve(self, query, assets, semantic_limit=10): self.called = True; return [a for a in assets if a.logic_area_id == "la.semantic"]
    class Reranker:
        def __init__(self): self.called = False
        def rerank(self, query, assets, context): self.called = True; return SimpleNamespace(selected_assets=assets, evidence_trace=[])
    retriever, reranker = Retriever(), Reranker()
    loaded = SimpleNamespace(edsl_tree=tree)
    node = EdslProjectContextResolver().resolve(request(path="$.nodes[0]"), loaded)
    block = LogicAreaContextResolver(retriever, reranker).resolve(request(path="$.nodes[0]"), loaded, node)
    assert retriever.called and reranker.called
    assert block.logic_area_ids == ["la.semantic"]
