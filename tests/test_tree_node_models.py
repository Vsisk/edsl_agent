from models import TreeNodeTerm


def test_simple_leaf_clears_iter_local_context():
    node = TreeNodeTerm.model_validate(
        {
            "tree_node_type": "simple_leaf",
            "iter_local_context": [{"name": "illegal"}],
        }
    )

    assert node.iter_local_context is None


def test_parent_defaults_are_not_shared():
    first = TreeNodeTerm(tree_node_type="parent")
    second = TreeNodeTerm(tree_node_type="parent")

    first.children.append(TreeNodeTerm(tree_node_type="simple_leaf"))

    assert second.children == []


def test_ab_content_type_matches_outer_type():
    node = TreeNodeTerm.model_validate(
        {
            "tree_node_type": "ab_pivot_table",
            "ab_content": {},
        }
    )

    assert node.ab_content.tree_node_type == "ab_pivot_table"
