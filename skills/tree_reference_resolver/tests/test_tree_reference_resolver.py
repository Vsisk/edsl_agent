from skills.tree_reference_resolver import LLMReranker, TreeReferenceResolveInput, TreeReferenceResolver


def request(sample_tree, **kwargs):
    tree, target = sample_tree
    return TreeReferenceResolveInput(target_node=target, target_node_path="$.mapping_content.children[1]", tree_json=tree, **kwargs)


def test_parent_list_is_selected_and_local_fallback_is_explained(sample_tree):
    result = TreeReferenceResolver().resolve(request(sample_tree, query="查找订户列表", expected_node_types=["parent_list"]))
    assert result.success and result.selected.node_id == "list-1"
    assert result.selected.tree_node_type == "parent_list"
    assert result.selected.match_reason and result.selected.evidence
    assert any(e.source == "fallback" for e in result.selected.raw_evidence)


def test_no_candidate_returns_fixed_reason(sample_tree):
    tree, _ = sample_tree
    result = TreeReferenceResolver().resolve(TreeReferenceResolveInput(target_node={"node_id": "external"}, query="完全无关的火星术语", tree_json=tree))
    assert not result.success and result.failure_reason == "NO_CANDIDATE"


def test_all_invalid_candidates_return_fixed_reason(sample_tree):
    result = TreeReferenceResolver().resolve(request(sample_tree, query="TARGET", expected_node_types=["container"], debug=True))
    assert not result.success and result.failure_reason == "NO_VALID_REFERENCE_NODE"
    assert result.debug_info["validation_errors"]


def test_llm_unknown_selection_falls_back_to_local_ranking(sample_tree):
    class BadClient:
        def complete_json(self, prompt, **kwargs):
            return {"selected_node_id": "invented", "selected_json_path": "$.invented"}

    resolver = TreeReferenceResolver(llm_reranker=LLMReranker(BadClient()))
    result = resolver.resolve(request(sample_tree, query="订户列表", expected_node_types=["parent_list"]))
    assert result.success and result.selected.node_id == "list-1"


def test_ab_query_only_selects_node_with_ab_content(sample_tree):
    result = TreeReferenceResolver().resolve(request(sample_tree, query="费用表 pivot 分组汇总"))
    assert result.success and result.selected.node_id == "ab-1"
