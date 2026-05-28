import unittest

from agent.models import ValueLogicRequest
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.value_logic_generator import ValueLogicGenerator
from tests.test_environment import FakeResourceFilter, sample_edsl_tree_payload


class FakePlanner:
    def __init__(self):
        self.calls = []

    def plan(self, *, node_info, user_query, filtered_env):
        self.calls.append(
            {
                "node_info": node_info,
                "user_query": user_query,
                "filtered_env": filtered_env,
            }
        )
        return Plan.model_validate(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "select_one",
                            "bo": "BB_PREP_SUB",
                            "filter": {
                                "type": "compare",
                                "op": "==",
                                "left": {"type": "context_path", "path": "it.ID"},
                                "right": {"type": "context_path", "path": "$ctx$.id"},
                            },
                        },
                    }
                ]
            }
        )


class FakeDifficultyRouter:
    def __init__(self, is_simple: bool):
        self.is_simple = is_simple
        self.calls = []

    def can_plan_with_context_only(self, *, node_info, user_query):
        self.calls.append(
            {
                "node_info": node_info,
                "user_query": user_query,
            }
        )
        return self.is_simple


class ValueLogicGeneratorTest(unittest.TestCase):
    def test_simple_leaf_generates_expression_by_existing_plan(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter(
                {
                    "bo": [{"resource_id": "bo.0000"}],
                    "function": [],
                    "local_context": [],
                    "global_context": [],
                }
            ),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={
                    "node_id": "node-1",
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "SUB_INFO"},
                    "annotation": "user information node",
                },
                query="query one prep sub by id",
            )
        )

        self.assertEqual(result.node_id, "node-1")
        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.expression, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(planner.calls[0]["node_info"].node_path, "$.mapping_content.children[1]")
        self.assertEqual(planner.calls[0]["node_info"].node_name, "SUB_INFO")
        self.assertEqual(planner.calls[0]["user_query"], "query one prep sub by id")

    def test_simple_context_only_requirement_filters_context_without_bo_or_functions(self):
        planner = FakePlanner()
        resource_filter = FakeResourceFilter(
            {
                "bo": [{"resource_id": "bo.0000"}],
                "function": [{"resource_id": "func.0001"}],
                "local_context": [{"resource_id": "local.0002"}],
                "global_context": [{"resource_id": "ctx.0001"}],
            }
        )
        difficulty_router = FakeDifficultyRouter(is_simple=True)
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=resource_filter,
            llm_difficulty_router=difficulty_router,
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1]",
                node={
                    "node_id": "node-1",
                    "tree_node_type": "simple_leaf",
                    "xml_name_property": {"xml_name": "SUB_INFO"},
                    "annotation": "user information node",
                },
                query="assign CUST_ID from subId context directly",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        filtered_env = planner.calls[0]["filtered_env"]
        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(len(resource_filter.calls), 1)
        self.assertEqual(difficulty_router.calls[0]["node_info"].node_name, "SUB_INFO")
        self.assertEqual(difficulty_router.calls[0]["user_query"], "assign CUST_ID from subId context directly")
        self.assertEqual(resource_filter.calls[0]["limits"]["bo"], 0)
        self.assertEqual(resource_filter.calls[0]["limits"]["function"], 0)
        self.assertEqual(resource_filter.calls[0]["candidates"]["bo"], [])
        self.assertEqual(resource_filter.calls[0]["candidates"]["function"], [])
        self.assertEqual(filtered_env.selected_local_context_ids[0], "local.0002")
        self.assertEqual(filtered_env.selected_global_context_ids[0], "ctx.0001")
        self.assertEqual(filtered_env.selected_bo_ids, [])
        self.assertEqual(filtered_env.selected_function_ids, [])

    def test_summary_field_returns_summary_result_without_calling_plan(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1].fields[0]",
                is_ab=True,
                node={
                    "node_id": "amount-total",
                    "tree_node_type": "field",
                    "field_type": "summary",
                    "summary_type": "sum",
                    "detail_field": "AMOUNT",
                    "xml_name_property": {"xml_name": "TOTAL_AMOUNT"},
                },
                query="sum detail amount",
            )
        )

        self.assertEqual(result.node_id, "amount-total")
        self.assertEqual(result.logic_type, "summary")
        self.assertIsNone(result.expression)
        self.assertEqual(result.source.source_type, "detail_field")
        self.assertEqual(result.source.summary_type, "sum")
        self.assertEqual(result.source.detail_field, "AMOUNT")
        self.assertEqual(planner.calls, [])

    def test_ab_sql_field_maps_from_parent_sql_bo_field_when_query_requests_direct_mapping(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1].fields[1]",
                is_ab=True,
                node={
                    "node_id": "normal-field",
                    "tree_node_type": "field",
                    "xml_name_property": {"xml_name": "LOG_ID"},
                },
                parent_node={
                    "node_id": "ab-parent",
                    "is_ab": True,
                    "ab_content": {
                        "data_source": {
                            "data_source_type": "sql",
                            "sql_query": {
                                "bo_name": "BB_BAK_TRANS",
                            },
                        },
                    },
                },
                query="directly map LOG_ID from table field",
            )
        )

        self.assertEqual(result.logic_type, "bo_field_mapping")
        self.assertEqual(result.expression, "LOG_ID")
        self.assertEqual(result.source.source_type, "bo")
        self.assertEqual(result.source.bo_name, "BB_BAK_TRANS")
        self.assertEqual(result.source.bo_field, "LOG_ID")
        self.assertEqual(planner.calls, [])

    def test_ab_sql_field_uses_plan_when_query_requires_more_than_field_mapping(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1].fields[1]",
                is_ab=True,
                node={
                    "node_id": "normal-field",
                    "tree_node_type": "field",
                    "xml_name_property": {"xml_name": "LOG_ID"},
                },
                parent_node={
                    "node_id": "ab-parent",
                    "is_ab": True,
                    "ab_content": {
                        "data_source": {
                            "data_source_type": "sql",
                            "sql_query": {
                                "bo_name": "BB_BAK_TRANS",
                            },
                        },
                    },
                },
                query="derive a formatted LOG_ID with fallback when missing",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(result.expression, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(len(planner.calls), 1)

    def test_ab_sql_field_falls_back_to_plan_when_bo_field_not_found(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1].fields[1]",
                is_ab=True,
                node={
                    "node_id": "normal-field",
                    "tree_node_type": "field",
                    "xml_name_property": {"xml_name": "MISSING_FIELD"},
                },
                parent_node={
                    "node_id": "ab-parent",
                    "is_ab": True,
                    "ab_content": {
                        "data_source": {
                            "data_source_type": "sql",
                            "sql_query": {
                                "bo_name": "BB_BAK_TRANS",
                            },
                        },
                    },
                },
                query="map or derive missing field",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(result.expression, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(len(planner.calls), 1)

    def test_ab_non_sql_field_does_not_read_nested_bo_name(self):
        planner = FakePlanner()
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=planner,
        )

        result = generator.generate(
            ValueLogicRequest(
                site_id="site1",
                project_id="project1",
                node_path="$.mapping_content.children[1].fields[1]",
                is_ab=True,
                node={
                    "node_id": "normal-field",
                    "tree_node_type": "field",
                    "xml_name_property": {"xml_name": "LOG_ID"},
                },
                parent_node={
                    "node_id": "ab-parent",
                    "is_ab": True,
                    "ab_content": {
                        "data_source": {
                            "data_source_type": "expression",
                            "sql_query": {
                                "bo_name": "SHOULD_NOT_BE_USED",
                            },
                        },
                    },
                },
                query="derive log id",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(len(planner.calls), 1)


if __name__ == "__main__":
    unittest.main()
