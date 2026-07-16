from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent.context_manager.errors import ContextBuildError, EDSL_NODE_NOT_FOUND, INVALID_LLM_OUTPUT, RULE_FILE_MISSING
from agent.context_manager.models import BuildContextRequest
from agent.context_manager.resolvers import EdslProjectContextResolver, GlobalContextResolver, LogicAreaContextResolver, OOTBContextResolver, SiteKnowledgeContextResolver


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
            {"node_id": "parent", "tree_node_type": "parent_list", "local_context": [{"property_name": "accountId", "annotation": "account"}], "iter_local_context": [{"property_name": "line", "annotation": "line"}], "children": [
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
    assert block.visible_iter_context[0]["context_name"] == "$local$.line"
    assert block.fee_table_summary["group_by_fields"] == ["category"]
    assert block.fee_table_summary["group_region"] == {"group_related_fields": ["region"]}
    assert block.existing_bo_ids == []
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


def test_simple_leaf_summary_is_strict_and_uses_project_truth():
    leaf = {"node_id": "leaf", "tree_node_type": "simple_leaf", "xml_name_property": {"xml_name": "AMOUNT"}, "annotation": "project annotation", "edsl_semi_struct": {"sa": "amount"}, "data_type_config": {"data_type": "money"}, "data_expresssion": {"expression": "legacy"}, "reference_logic_area_id_list": ["la"]}
    tree = {"mapping_content": {"node_id": "root", "tree_node_type": "parent", "children": [leaf]}}
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={})
    block = EdslProjectContextResolver().resolve(request("$.mapping_content.children[0]"), loaded)
    assert block.is_simple_leaf is True
    assert block.simple_leaf_summary == {key: leaf[key] for key in ("xml_name_property", "annotation", "edsl_semi_struct", "data_type_config", "data_expresssion", "reference_logic_area_id_list")}
    assert block.current_node["annotation"] == "project annotation"
    non_leaf = EdslProjectContextResolver().resolve(request("$.mapping_content"), loaded)
    assert non_leaf.is_simple_leaf is False
    assert non_leaf.simple_leaf_summary is None


@pytest.mark.parametrize(
    ("node_type", "content", "expected_summaries"),
    [
        ("ab_pivot_table", {"data_source": {"data_source_type": "sql", "sql_query": {"bo_name": "PIVOT_BO", "naming_sql_list": [{"naming_sql_content": {"naming_sql": "pivot.sql"}}]}}, "group_by_fields": ["g"], "group_region": {"group_related_fields": ["r"], "sum_fields": ["sum"]}, "summary_fields": ["top"]}, ["top", "sum"]),
        ("ab_two_level_table", {"data_source": {"data_source_type": "sql", "sql_query": {"bo_name": "TWO_BO", "naming_sql_id": "two.id"}}, "group_by_fields": ["g"], "group_region": {"group_related_fields": ["r"], "summary_fields": ["nested"]}, "detail_region": {"detail_fields": ["d"]}, "summary_fields": ["top"]}, ["top", "nested"]),
        ("ab_single_mapping_table", {"data_source": {"data_source_type": "sql", "sql_query": {"bo_name": "SINGLE_BO", "naming_sql": "single.sql"}}, "detail_fields": ["d"], "summary_fields": ["top"]}, ["top"]),
    ],
)
def test_fee_table_summaries_follow_real_type_shapes(node_type, content, expected_summaries):
    node = {"node_id": "fee", "tree_node_type": node_type, "ab_content": content}
    tree = {"mapping_content": node}
    before = deepcopy(tree)
    block = EdslProjectContextResolver().resolve(request("$.mapping_content"), SimpleNamespace(edsl_tree=tree, bo_registry={}))
    assert block.fee_table_summary["data_source"] == content["data_source"]
    assert block.fee_table_summary["summary_fields"] == expected_summaries
    assert block.existing_data_source == content["data_source"]
    assert block.existing_bo_name == content["data_source"]["sql_query"]["bo_name"]
    assert block.existing_naming_sql_ids
    assert tree == before


def test_semantic_fallback_enriches_query_without_mutating(tree):
    tree["nodes"][0].update({"xml_name_property": {"xml_name": "ROOT_XML"}, "annotation": "root annotation"})
    before = deepcopy(tree)
    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): self.query = query; return assets[:1]
    class Reranker:
        def rerank(self, query, assets, context): self.query = query; return SimpleNamespace(selected_assets=assets, evidence_trace=[])
    retriever, reranker = Retriever(), Reranker()
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={})
    node = EdslProjectContextResolver().resolve(request("$.nodes[0]"), loaded)
    LogicAreaContextResolver(retriever, reranker).resolve(request("$.nodes[0]"), loaded, node)
    assert retriever.query == reranker.query
    assert "charge fee" in retriever.query and "ROOT_XML" in retriever.query and "root annotation" in retriever.query
    assert tree == before


def test_error_resolution_does_not_mutate_tree(tree):
    before = deepcopy(tree)
    with pytest.raises(ContextBuildError):
        EdslProjectContextResolver().resolve(request("$.[invalid"), SimpleNamespace(edsl_tree=tree, bo_registry={}))
    assert tree == before


def test_logic_error_path_does_not_mutate_tree(tree):
    before = deepcopy(tree)
    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets
    class BrokenReranker:
        def rerank(self, query, assets, context): raise RuntimeError("rerank failed")
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={})
    node = EdslProjectContextResolver().resolve(request("$.nodes[0]"), loaded)
    with pytest.raises(RuntimeError, match="rerank failed"):
        LogicAreaContextResolver(Retriever(), BrokenReranker()).resolve(request("$.nodes[0]"), loaded, node)
    assert tree == before


@pytest.mark.parametrize("returned", ["unknown", "duplicate", "malformed"])
def test_logic_reranker_rejects_noncanonical_selections(tree, returned):
    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets[:2]
    class Reranker:
        def rerank(self, query, assets, context):
            if returned == "unknown":
                selected = [assets[0].model_copy(update={"asset_id": "logic_area:invented", "logic_area_id": "invented"})]
            elif returned == "duplicate":
                selected = [assets[0], assets[0]]
            else:
                selected = [object()]
            return SimpleNamespace(selected_assets=selected, evidence_trace=[])
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={})
    node = EdslProjectContextResolver().resolve(request("$.nodes[0]"), loaded)
    with pytest.raises(ContextBuildError) as exc:
        LogicAreaContextResolver(Retriever(), Reranker()).resolve(request("$.nodes[0]"), loaded, node)
    assert exc.value.code == INVALID_LLM_OUTPUT


def test_logic_reranker_same_id_uses_canonical_content(tree):
    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets[:1]
    class Reranker:
        def rerank(self, query, assets, context):
            forged = assets[0].model_copy(update={"content": {"id": "la.node", "name": "forged"}, "index_text": "forged"})
            return SimpleNamespace(selected_assets=[forged], evidence_trace=[])
    loaded = SimpleNamespace(edsl_tree=tree, bo_registry={})
    node = EdslProjectContextResolver().resolve(request("$.nodes[0]"), loaded)
    block = LogicAreaContextResolver(Retriever(), Reranker()).resolve(request("$.nodes[0]"), loaded, node)
    assert block.assets[0].content["name"] == "Charge"


def test_fee_summary_does_not_expand_malformed_dicts_or_strings():
    node = {"node_id": "fee", "tree_node_type": "ab_two_level_table", "ab_content": {"detail_fields": "abc", "group_by_fields": {"bad": "shape"}, "summary_fields": "xyz", "group_region": {"summary_fields": {"bad": "shape"}}, "detail_region": {"detail_fields": "chars"}}}
    block = EdslProjectContextResolver().resolve(request("$.mapping_content"), SimpleNamespace(edsl_tree={"mapping_content": node}, bo_registry={}))
    assert block.fee_table_summary["detail_fields"] == []
    assert block.fee_table_summary["group_by_fields"] == []
    assert block.fee_table_summary["summary_fields"] == []
    assert block.fee_table_summary["group_region"] == {"summary_fields": {"bad": "shape"}}


def test_missing_reference_file_is_nonfatal(tmp_path):
    block = OOTBContextResolver(tmp_path / "missing.jsonl").resolve(request(), {})
    assert block.candidates == []
    assert block.evidence_trace[0].action == "source_missing"


def test_site_cases_are_filtered_before_recall(tmp_path):
    path = tmp_path / "site.jsonl"
    path.write_text(
        '\n'.join([
            '{"case_id":"match","site_id":"s","project_id":"p","description":"charge"}',
            '{"case_id":"other-site","site_id":"x","project_id":"p","description":"charge"}',
            '{"case_id":"other-project","site_id":"s","project_id":"x","description":"charge"}',
        ]),
        encoding="utf-8",
    )

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10):
            self.seen = assets
            return assets

    class Reranker:
        def rerank(self, query, assets, context):
            return SimpleNamespace(selected_assets=assets, evidence_trace=[])

    retriever = Retriever()
    block = SiteKnowledgeContextResolver(path, retriever, Reranker()).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["match"]
    assert [item.content["case_id"] for item in retriever.seen] == ["match"]


def test_reference_jsonl_skips_bad_records_and_builds_semantic_candidate(tmp_path):
    path = tmp_path / "ootb.jsonl"
    valid = {
        "case_id": "fee-case", "description": "fee lookup", "node_pattern": "pivot table",
        "logic_area_terms": ["billing", "charge"], "query_terms": ["account", "fee"],
        "selected_bo": {"bo_name": "ChargeBO"},
        "selected_sql": {"naming_sql_id": "sql.fee", "sql_name": "findFee", "param_list": [{"name": "accountId"}]},
        "param_hints": {"accountId": "$ctx$.account"}, "bindings": [{"param": "accountId", "source": "$ctx$.account"}],
        "source": "curated", "evidence": ["manually verified"],
    }
    path.write_bytes(b'{bad}\n[]\n\xff\xfe\n' + json.dumps(valid).encode("utf-8") + b'\n' + b'x' * 70000 + b'\n')
    before = deepcopy(valid)

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets
    class Reranker:
        def rerank(self, query, assets, context): return SimpleNamespace(selected_assets=assets, evidence_trace=[])

    block = OOTBContextResolver(path, Retriever(), Reranker()).resolve(request(), {"node": "safe"})
    item = block.candidates[0]
    assert item.asset.content == before
    assert all(term in item.asset.index_text for term in ("fee lookup", "pivot table", "billing", "account", "ChargeBO", "sql.fee", "$ctx$.account"))
    assert item.candidate.bo_name == "ChargeBO" and item.candidate.naming_sql_id == "sql.fee"
    assert item.candidate.param_list == [{"name": "accountId"}]
    assert item.candidate.retrieval_metadata["bindings"] == valid["bindings"]
    assert item.evidence[0].evidence == "manually verified"
    assert sum(event.action == "record_skipped" for event in block.evidence_trace) == 4
    assert valid == before


def test_reference_schema_invalid_object_is_skipped_without_losing_valid_case(tmp_path):
    path = tmp_path / "mixed.jsonl"
    invalid = {"case_id": "bad", "description": "sensitive customer wording", "selected_bo": "BO", "selected_sql": "sql.bad", "param_list": ["not-an-object"]}
    wrong_selected_type = {"case_id": "bad-shape", "selected_bo": ["BO"], "selected_sql": {"sql_name": "query"}}
    valid = {"case_id": "good", "description": "valid", "selected_bo": "BO", "selected_sql": "sql.good", "param_list": [{"name": "accountId"}]}
    path.write_text("\n".join(json.dumps(item) for item in (invalid, wrong_selected_type, valid)) + "\n", encoding="utf-8")

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets
    class Reranker:
        def rerank(self, query, assets, context): return SimpleNamespace(selected_assets=assets, evidence_trace=[])

    block = OOTBContextResolver(path, Retriever(), Reranker()).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["good"]
    skipped = [item for item in block.evidence_trace if item.action == "record_skipped"]
    assert [item.asset_id for item in skipped] == ["ootb_case:bad", "ootb_case:bad-shape"]
    assert invalid["description"] not in skipped[0].evidence


def test_reference_deep_json_is_skipped_and_valid_neighbor_survives(tmp_path):
    path = tmp_path / "deep.jsonl"
    deep = '{"case_id":"deep","description":' + '[' * 1100 + '"secret"' + ']' * 1100 + '}\n'
    valid = '{"case_id":"good","description":"usable"}\n'
    path.write_text(deep + valid, encoding="utf-8")

    block = OOTBContextResolver(path).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["good"]
    skipped = [item for item in block.evidence_trace if item.action == "record_skipped"]
    assert len(skipped) == 1 and "secret" not in skipped[0].evidence


def test_reference_decoder_recursion_error_is_safely_skipped(tmp_path, monkeypatch):
    path = tmp_path / "decoder.jsonl"
    path.write_text('{"case_id":"deep"}\n{"case_id":"good","description":"usable"}\n', encoding="utf-8")
    from agent.context_manager.resolvers import reference_cases
    real_loads = reference_cases.json.loads
    calls = 0

    def loads(value):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RecursionError("decoder exposed sensitive input")
        return real_loads(value)

    monkeypatch.setattr(reference_cases.json, "loads", loads)
    block = OOTBContextResolver(path).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["good"]
    skipped = [item for item in block.evidence_trace if item.action == "record_skipped"]
    assert len(skipped) == 1 and "sensitive" not in skipped[0].evidence


def test_reference_semantic_traversal_is_depth_bounded_and_neighbor_survives(tmp_path):
    path = tmp_path / "semantic-depth.jsonl"
    nested = '[' * 1100 + '"deep secret"' + ']' * 1100
    path.write_text(
        '{"case_id":"deep","query_terms":' + nested + '}\n'
        '{"case_id":"good","description":"usable"}\n',
        encoding="utf-8",
    )

    block = OOTBContextResolver(path).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["deep", "good"]
    assert "deep secret" not in block.candidates[0].asset.index_text
    assert len(block.candidates[0].asset.index_text) <= 16_000


@pytest.mark.parametrize("kind", ["unknown", "duplicate"])
def test_reference_retriever_enforces_canonical_boundary(tmp_path, kind):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"one","description":"first"}\n{"case_id":"two","description":"second"}\n', encoding="utf-8")

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10):
            if kind == "unknown":
                return [assets[0].model_copy(update={"asset_id": "ootb_case:invented"})]
            return [assets[0], assets[0]]

    with pytest.raises(ContextBuildError) as exc:
        OOTBContextResolver(path, Retriever()).resolve(request(), {})
    assert exc.value.code == INVALID_LLM_OUTPUT


@pytest.mark.parametrize("kind", ["unknown", "duplicate", "malformed"])
def test_reference_reranker_enforces_canonical_boundary(tmp_path, kind):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"one","description":"original"}\n{"case_id":"two","description":"second"}\n', encoding="utf-8")

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets
    class Reranker:
        def rerank(self, query, assets, context):
            if kind == "unknown": selected = [assets[0].model_copy(update={"asset_id": "ootb_case:invented"})]
            elif kind == "duplicate": selected = [assets[0], assets[0]]
            else: selected = [object()]
            return SimpleNamespace(selected_assets=selected, evidence_trace=[])

    with pytest.raises(ContextBuildError) as exc:
        OOTBContextResolver(path, Retriever(), Reranker()).resolve(request(), {})
    assert exc.value.code == INVALID_LLM_OUTPUT


def test_reference_reranker_order_and_forged_content_are_canonicalized(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"one","description":"original"}\n{"case_id":"two","description":"second"}\n', encoding="utf-8")

    class Retriever:
        def retrieve(self, query, assets, semantic_limit=10): return assets
    class Reranker:
        def rerank(self, query, assets, context):
            forged = assets[0].model_copy(update={"content": {"case_id": "one", "description": "forged"}})
            return SimpleNamespace(selected_assets=[assets[1], forged], evidence_trace=[])

    block = OOTBContextResolver(path, Retriever(), Reranker()).resolve(request(), {})
    assert [item.asset.content["case_id"] for item in block.candidates] == ["two", "one"]
    assert block.candidates[1].asset.content["description"] == "original"
    assert [event.asset_id for event in block.evidence_trace if event.action == "case_selected"] == ["ootb_case:two", "ootb_case:one"]
