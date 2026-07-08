from skills.tree_reference_resolver import CandidateMerger, CandidateRetriever, NodeIndexBuilder, SearchSpecBuilder, TreeReferenceResolveInput


def test_explicit_xml_path_produces_exact_match(sample_tree):
    tree, target = sample_tree
    request = TreeReferenceResolveInput(target_node=target, target_node_path="$.mapping_content.children[1]", query="use BILL_INFO/CUSTOMERS", tree_json=tree)
    index = NodeIndexBuilder().build(tree)
    candidates = CandidateMerger().merge(CandidateRetriever().retrieve(request, SearchSpecBuilder().build(request, index), index), request)
    assert candidates[0].node_id == "list-1"
    assert any(item.source == "exact" for item in candidates[0].raw_evidence)


def test_structural_candidates_are_recalled(sample_tree):
    tree, target = sample_tree
    request = TreeReferenceResolveInput(target_node=target, query="find list", tree_json=tree, expected_node_types=["parent_list"])
    index = NodeIndexBuilder().build(tree)
    candidates = CandidateRetriever().retrieve(request, SearchSpecBuilder().build(request, index), index)
    assert any(item.node_id == "list-1" and any(e.source == "structural" for e in item.raw_evidence) for item in candidates)
