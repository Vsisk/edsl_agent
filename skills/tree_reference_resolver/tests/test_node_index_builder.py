from skills.tree_reference_resolver import NodeIndexBuilder


def test_dfs_builds_paths_and_child_names(sample_tree):
    tree, _ = sample_tree
    index = NodeIndexBuilder().build(tree)
    by_id = {item.node_id: item for item in index}
    assert by_id["root"].json_path == "$.mapping_content"
    assert by_id["root"].child_xml_names == ["CUSTOMERS", "TARGET", "FEE_PIVOT"]
    assert by_id["leaf-1"].json_path == "$.mapping_content.children[1].children[0]"
    assert by_id["leaf-1"].xml_path == "BILL_INFO/TARGET/CUSTOMER_ID"
    assert by_id["ab-1"].ab_bo_name == "FeeBO"


def test_tree_without_mapping_content_is_supported():
    tree = {"tree_node_type": "root", "xml_name_property": {"xml_name": "ROOT"}}
    entry = NodeIndexBuilder().build(tree)[0]
    assert entry.json_path == "$" and entry.xml_path == "ROOT"
