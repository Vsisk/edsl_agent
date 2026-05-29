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

        environment = build_filtered_environment(
            node_info,
            "use local context",
            loaded,
            llm_resource_filter=FailingResourceFilter(),
        )

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
            llm_resource_filter=FailingResourceFilter(),
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

    def test_uses_llm_resource_filter_to_rerank_candidates(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
            description="customer mask",
        )
        llm_filter = FakeResourceFilter(
            {
                "bo": [{"resource_id": "bo.0000", "reason": "transaction semantic match"}],
                "function": [{"resource_id": "func.0001", "reason": "mask semantic match"}],
                "local_context": [{"resource_id": "local.0002", "reason": "iter id semantic match"}],
                "global_context": [{"resource_id": "ctx.0001", "reason": "customer context match"}],
            }
        )

        environment = build_filtered_environment(
            node_info,
            "mask customer call and query transaction end date",
            loaded,
            top_global_context=1,
            top_local_context=1,
            top_bo=1,
            top_function=1,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(environment.selected_bo_ids, ["bo.0000"])
        self.assertEqual(environment.selected_function_ids, ["func.0001"])
        self.assertEqual(environment.selected_local_context_ids, ["local.0002"])
        self.assertEqual(environment.selected_global_context_ids, ["ctx.0001"])
        self.assertEqual(llm_filter.calls[0]["limits"]["bo"], 1)
        self.assertLessEqual(len(llm_filter.calls[0]["candidates"]["bo"]), 5)

    def test_llm_tool_search_selects_bo_by_naming_sql_name_before_semantic_filter(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
        )
        llm_filter = FakeResourceFilter(
            {},
            search_commands={
                "commands": [
                    {
                        "tool": "resource_keyword_search",
                        "group": "bo",
                        "keyword": "BB_BAK_TRANS_queryDataLoadData",
                    }
                ]
            },
        )

        environment = build_filtered_environment(
            node_info,
            "use BB_BAK_TRANS_queryDataLoadData to query data",
            loaded,
            top_bo=1,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(environment.selected_bo_ids, ["bo.0000"])
        self.assertEqual([bo.bo_name for bo in environment.selected_bos], ["BB_BAK_TRANS"])
        self.assertEqual(len(llm_filter.search_calls), 1)
        self.assertEqual(llm_filter.calls, [])

    def test_llm_tool_search_selects_function_and_context_by_resource_name(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
        )
        llm_filter = FakeResourceFilter(
            {},
            search_commands={
                "commands": [
                    {
                        "tool": "resource_keyword_search",
                        "group": "global_context",
                        "keyword": "$ctx$.billStatement.CUST_ID",
                    },
                    {
                        "tool": "resource_keyword_search",
                        "group": "function",
                        "keyword": "CustCallMask",
                    },
                ]
            },
        )

        environment = build_filtered_environment(
            node_info,
            "set value from $ctx$.billStatement.CUST_ID then call CustCallMask",
            loaded,
            top_global_context=1,
            top_function=1,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(environment.selected_global_context_ids, ["ctx.0001"])
        self.assertEqual(environment.selected_function_ids, ["func.0001"])
        self.assertEqual(len(llm_filter.search_calls), 1)
        self.assertEqual(llm_filter.calls, [])

    def test_falls_back_to_string_ranked_candidates_for_invalid_llm_ids(self):
        loaded = ResourceLoader().load_resource("site1", "project1", sample_edsl_tree_payload())
        node_info = NodeDef(
            node_id="node-1",
            node_path="$.mapping_content.children[1]",
            node_name="SUB_INFO",
            description="customer mask",
        )
        llm_filter = FakeResourceFilter(
            {
                "bo": [{"resource_id": "missing.bo", "reason": "not a candidate"}],
                "function": [],
            }
        )

        environment = build_filtered_environment(
            node_info,
            "mask customer call and query transaction end date",
            loaded,
            top_bo=1,
            top_function=1,
            llm_resource_filter=llm_filter,
        )

        self.assertEqual(environment.selected_bo_ids, ["bo.0000"])
        self.assertEqual(environment.selected_function_ids, ["func.0001"])


class FakeResourceFilter:
    def __init__(self, result, search_commands=None):
        self.result = result
        self.search_commands = search_commands or {"commands": []}
        self.calls = []
        self.search_calls = []

    def plan_resource_search_commands(self, *, node_info, user_query, search_space, limits):
        self.search_calls.append(
            {
                "node_info": node_info,
                "user_query": user_query,
                "search_space": search_space,
                "limits": limits,
            }
        )
        return self.search_commands

    def filter_resources(self, *, node_info, user_query, candidates, limits):
        self.calls.append(
            {
                "node_info": node_info,
                "user_query": user_query,
                "candidates": candidates,
                "limits": limits,
            }
        )
        return self.result


class FailingResourceFilter:
    def filter_resources(self, *, node_info, user_query, candidates, limits):
        raise RuntimeError("LLM should not be called in unit tests")


if __name__ == "__main__":
    unittest.main()
