from skills.tree_reference_resolver import NodeIndexBuilder, ReferenceSearchSpec, ReferenceValidator, TreeReferenceCandidate, TreeReferenceResolveInput


def candidate(entry):
    return TreeReferenceCandidate(node_id=entry.node_id, json_path=entry.json_path, xml_path=entry.xml_path, tree_node_type=entry.tree_node_type)


def test_target_and_descendant_are_invalid(sample_tree):
    tree, target = sample_tree
    index = NodeIndexBuilder().build(tree)
    request = TreeReferenceResolveInput(target_node=target, target_node_path="$.mapping_content.children[1]", query="q", tree_json=tree)
    validator, spec = ReferenceValidator(), ReferenceSearchSpec()
    for node_id in ("target-1", "leaf-1"):
        entry = next(item for item in index if item.node_id == node_id)
        valid, errors = validator.validate(candidate(entry), request, spec, index)
        assert not valid and errors


def test_parent_list_and_ab_require_structure(sample_tree):
    tree, target = sample_tree
    index = NodeIndexBuilder().build(tree)
    validator = ReferenceValidator()
    request = TreeReferenceResolveInput(target_node=target, query="q", tree_json=tree)
    list_entry = next(item for item in index if item.node_id == "list-1")
    assert validator.validate(candidate(list_entry), request, ReferenceSearchSpec(expected_node_types=["parent_list"]), index)[0]
    ab_entry = next(item for item in index if item.node_id == "ab-1")
    assert validator.validate(candidate(ab_entry), request, ReferenceSearchSpec(expected_node_types=["ab"]), index)[0]
