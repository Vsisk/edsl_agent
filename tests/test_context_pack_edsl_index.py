from agent.context_pack.indexing.edsl_tree import EdslIndexBuilder


def tree_fixture():
    return {
        "mapping_content": {
            "node_id": "root",
            "tree_node_type": "parent",
            "xml_name_property": {"xml_name": "ROOT"},
            "children": [
                {
                    "node_id": "customers",
                    "tree_node_type": "parent_list",
                    "annotation": "客户列表",
                    "xml_name_property": {"xml_name": "CUSTOMERS"},
                    "local_context": [{"property_name": "title", "annotation": "称谓"}],
                    "iter_local_context": [{"property_name": "customer", "annotation": "当前客户"}],
                    "children": [
                        {
                            "node_id": "name-1",
                            "tree_node_type": "simple_leaf",
                            "annotation": "客户姓名",
                            "xml_name_property": {"xml_name": "NAME"},
                            "data_type_config": {"data_type": "String"},
                        },
                        {
                            "node_id": "name-2",
                            "tree_node_type": "simple_leaf",
                            "annotation": "备用姓名",
                            "xml_name_property": {"xml_name": "NAME"},
                        },
                        {
                            "node_id": "fees",
                            "tree_node_type": "ab_two_level_table",
                            "xml_name_property": {"xml_name": "FEES"},
                            "ab_content": {
                                "detail_fields": [{"field_name": "AMOUNT", "annotation": "金额"}],
                                "group_by_fields": [{"field_name": "TYPE", "annotation": "类型"}],
                                "summary_fields": [{"field_name": "TOTAL", "annotation": "合计"}],
                            },
                        },
                    ],
                }
            ],
        }
    }


def test_index_builds_nodes_fields_variables_and_paths():
    entries = EdslIndexBuilder().build(tree_fixture(), source_id="current-tree")

    by_id = {entry.item_id: entry for entry in entries}
    name_entries = [entry for entry in entries if entry.name == "NAME"]
    assert len(name_entries) == 2
    assert len({entry.json_path for entry in name_entries}) == 2
    assert all(entry.item_type == "field" for entry in name_entries)
    assert name_entries[0].xml_path == "ROOT/CUSTOMERS/NAME"
    assert name_entries[0].parent_node_id == "customers"
    assert name_entries[0].data_type == "String"
    assert {entry.field_role for entry in entries if entry.name in {"AMOUNT", "TYPE", "TOTAL"}} == {
        "detail", "group", "summary"
    }
    assert {entry.item_type for entry in entries if entry.name in {"title", "customer"}} == {"local", "iter"}
    assert len(by_id) == len(entries)


def test_index_content_is_bounded_and_does_not_embed_descendant_tree():
    entries = EdslIndexBuilder(max_content_chars=200).build(tree_fixture(), source_id="ootb")
    root = entries[0]

    assert len(str(root.content)) <= 250
    assert "children" not in root.content
    assert root.source_id == "ootb"
