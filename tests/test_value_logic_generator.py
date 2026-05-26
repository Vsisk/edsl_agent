import unittest

from agent.models import ValueLogicRequest
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.value_logic_generator import ValueLogicGenerator
from tests.test_environment import FakeResourceFilter


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
        self.assertTrue(any("summary expression generation" in item for item in result.diagnostics))

    def test_ab_sql_field_attempts_bo_mapping_then_falls_back_to_plan(self):
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
                query="map or derive log id",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(result.expression, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(len(planner.calls), 1)
        self.assertTrue(any("BO field mapping" in item for item in result.diagnostics))
        self.assertTrue(any("BB_BAK_TRANS" in item for item in result.diagnostics))

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
        self.assertFalse(any("BO field mapping" in item for item in result.diagnostics))
        self.assertFalse(any("SHOULD_NOT_BE_USED" in item for item in result.diagnostics))

    def test_unsupported_node_type_raises(self):
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=FakePlanner(),
        )

        with self.assertRaisesRegex(ValueError, "Unsupported node type"):
            generator.generate(
                ValueLogicRequest(
                    site_id="site1",
                    project_id="project1",
                    node_path="$.mapping_content.children[1]",
                    node={
                        "node_id": "unsupported",
                        "tree_node_type": "parent",
                    },
                    query="derive value",
                )
            )


if __name__ == "__main__":
    unittest.main()
