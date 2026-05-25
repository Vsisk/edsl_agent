import unittest

from agent.edsl_gen_entry import ValueLogicGenerator
from agent.models import ValueLogicRequest
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
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


class EDSLGenEntryTest(unittest.TestCase):
    def test_generate_value_logic_runs_from_request_to_expression(self):
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
                },
                query="query one prep sub by id",
            )
        )

        self.assertEqual(result.logic_type, "expression")
        self.assertEqual(result.expression, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(result.source.source_type, "plan")
        self.assertEqual(planner.calls[0]["node_info"].node_id, "node-1")
        self.assertEqual(planner.calls[0]["user_query"], "query one prep sub by id")
        self.assertEqual(planner.calls[0]["filtered_env"].selected_bo_ids, ["bo.0000"])

    def test_generate_value_logic_raises_when_generation_fails(self):
        generator = ValueLogicGenerator(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=FailingPlanner(),
        )

        with self.assertRaisesRegex(RuntimeError, "planner exploded"):
            generator.generate(
                ValueLogicRequest(
                    site_id="site1",
                    project_id="project1",
                    node_path="$.mapping_content.children[1]",
                    node={
                        "node_id": "node-1",
                        "tree_node_type": "simple_leaf",
                        "xml_name_property": {"xml_name": "SUB_INFO"},
                    },
                    query="will fail",
                )
            )


class FailingPlanner:
    def plan(self, *, node_info, user_query, filtered_env):
        raise RuntimeError("planner exploded")


if __name__ == "__main__":
    unittest.main()
