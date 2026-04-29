import unittest

from agent.environment.environment import build_filtered_environment
from agent.models import NodeDef
from agent.resource_manager.loader.resource_loader import ResourceLoader


def sample_edsl_tree_payload():
    return {
        "mapping_content": {
            "tree_node_type": "parent",
            "annotation": "root node",
            "xml_name_property": {
                "xml_name": "ROOT",
            },
            "local_context": [
                {
                    "property_name": "rootLocal",
                    "annotation": "root local context",
                    "return_type": {
                        "data_type": "basic",
                        "data_type_name": "STRING",
                        "is_list": False,
                    },
                }
            ],
            "children": [
                {
                    "tree_node_type": "simple_leaf",
                    "annotation": "release",
                },
                {
                    "tree_node_type": "parent_list",
                    "annotation": "user info",
                    "xml_name_property": {
                        "xml_name": "SUB_INFO",
                    },
                    "local_context": [
                        {
                            "property_name": "local_2",
                            "annotation": "desc_2",
                            "return_type": {
                                "data_type": "basic",
                                "data_type_name": "INT32",
                                "is_list": False,
                            },
                        }
                    ],
                    "iter_local_context": [
                        {
                            "property_name": "subId",
                            "annotation": "user id",
                            "return_type": {
                                "data_type": "basic",
                                "data_type_name": "INT64",
                                "is_list": False,
                            },
                        }
                    ],
                    "children": [],
                },
            ],
        }
    }


class EnvironmentBuilderTest(unittest.TestCase):
    def test_includes_ranked_visible_local_context_from_node_info(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
        )

        environment = build_filtered_environment(node_info, "use local context", loaded)

        self.assertEqual(
            [local_context.context_name for local_context in environment.visible_local_context],
            ["$local$.local_2", "$local$.rootLocal", "$iter$.subId"],
        )

    def test_filters_ranked_resources_by_weighted_tags(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
            description="customer mask",
        )

        environment = build_filtered_environment(
            node_info,
            "mask customer call and query transaction end date",
            loaded,
            top_global_context=2,
            top_local_context=2,
            top_bo=1,
            top_function=1,
        )

        self.assertEqual(environment.selected_bo_ids, ["bo.0000"])
        self.assertEqual([bo.bo_name for bo in environment.selected_bos], ["BB_BAK_TRANS"])
        self.assertEqual(environment.selected_function_ids, ["func.0001"])
        self.assertEqual([function.func_name for function in environment.selected_functions], ["CustCallMask"])
        self.assertLessEqual(len(environment.selected_global_contexts), 2)
        self.assertLessEqual(len(environment.visible_local_context), 2)
        self.assertEqual(
            environment.selected_local_context_ids,
            [local_context.resource_id for local_context in environment.visible_local_context],
        )


if __name__ == "__main__":
    unittest.main()
