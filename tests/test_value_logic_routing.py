import pytest

from agent.value_logic_routing import classify_value_logic_target


def test_simple_leaf_only_allows_expression():
    result = classify_value_logic_target({"tree_node_type": "simple_leaf"})

    assert result.kind == "simple_leaf"
    assert result.allowed_logic_types == ("edsl_expression",)
    assert result.priority == ("edsl_expression",)
    assert result.required_is_list is False


@pytest.mark.parametrize("tree_node_type", ["ab_pivot_table", "ab_two_level_table", "parent_list"])
def test_ab_container_prefers_sql_and_requires_list(tree_node_type):
    result = classify_value_logic_target({"node_id": "n1", "tree_node_type": tree_node_type})

    assert result.kind == "ab_container"
    assert result.allowed_logic_types == ("sql", "edsl_expression")
    assert result.priority == ("sql", "edsl_expression")
    assert result.required_is_list is True


def test_field_prefers_table_field():
    result = classify_value_logic_target({"field_id": "f1", "tree_node_type": "ab_pivot_table"})

    assert result.kind == "ab_field"
    assert result.allowed_logic_types == ("table_field", "edsl_expression")
    assert result.priority == ("table_field", "edsl_expression")
    assert result.required_is_list is False


def test_summary_field_stays_in_field_branch():
    result = classify_value_logic_target(
        {"field_id": "f1", "tree_node_type": "ab_pivot_table", "field_type": "summary"}
    )

    assert result.kind == "ab_field"
    assert result.is_summary is True
    assert result.allowed_logic_types == ("summary",)


def test_table_field_requires_field_id():
    result = classify_value_logic_target({"tree_node_type": "parent"})

    assert "table_field" not in result.allowed_logic_types


def test_invalid_unknown_tree_node_type_is_rejected():
    with pytest.raises(ValueError, match="unknown tree_node_type"):
        classify_value_logic_target({"node_id": "n1", "tree_node_type": "unknown"})
