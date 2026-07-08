import pytest


@pytest.fixture
def sample_tree():
    leaf = {
        "node_id": "leaf-1", "tree_node_type": "simple_leaf",
        "xml_name_property": {"xml_name": "CUSTOMER_ID"}, "annotation": "订户编号字段",
        "data_type_config": {"data_type": "string"},
    }
    target = {
        "node_id": "target-1", "tree_node_type": "container",
        "xml_name_property": {"xml_name": "TARGET"}, "children": [leaf],
    }
    customer_list = {
        "node_id": "list-1", "tree_node_type": "parent_list",
        "xml_name_property": {"xml_name": "CUSTOMERS"}, "annotation": "订户列表",
        "iter_local_context": [{"variable_name": "customer"}], "children": [],
    }
    ab = {
        "node_id": "ab-1", "tree_node_type": "ab",
        "xml_name_property": {"xml_name": "FEE_PIVOT"}, "annotation": "费用表分组汇总",
        "ab_content": {"data_source": {"data_source_type": "sql", "sql_query": {"bo_name": "FeeBO"}}},
    }
    root = {
        "node_id": "root", "tree_node_type": "root",
        "xml_name_property": {"xml_name": "BILL_INFO"},
        "children": [customer_list, target, ab],
    }
    return {"mapping_content": root}, target
