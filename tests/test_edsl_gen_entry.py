import unittest

from agent.edsl_gen_entry import DSLAgent
from agent.models import GenerateDSLRequest, NodeDef
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
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


class EDSLGenEntryTest(unittest.TestCase):
    def test_generate_dsl_runs_from_request_to_expression(self):
        planner = FakePlanner()
        agent = DSLAgent(
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

        response = agent.generate_dsl(
            GenerateDSLRequest(
                user_requirement="query one prep sub by id",
                node=NodeDef(
                    node_id="node-1",
                    node_path="$.mapping_content.children[1]",
                    node_name="SUB_INFO",
                ),
                site_id="site1",
                project_id="project1",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertTrue(response.success)
        self.assertEqual(response.dsl, "select_one(BB_PREP_SUB, it.ID == $ctx$.id)")
        self.assertEqual(response.failure_reason, "")
        self.assertEqual(planner.calls[0]["node_info"].node_id, "node-1")
        self.assertEqual(planner.calls[0]["user_query"], "query one prep sub by id")
        self.assertEqual(planner.calls[0]["filtered_env"].selected_bo_ids, ["bo.0000"])

    def test_generate_dsl_returns_failure_response_when_generation_fails(self):
        agent = DSLAgent(
            resource_loader=ResourceLoader(),
            llm_resource_filter=FakeResourceFilter({}),
            llm_planner=FailingPlanner(),
        )

        response = agent.generate_dsl(
            GenerateDSLRequest(
                user_requirement="will fail",
                node=NodeDef(
                    node_id="node-1",
                    node_path="$.mapping_content.children[1]",
                    node_name="SUB_INFO",
                ),
                site_id="site1",
                project_id="project1",
                edsl_tree=sample_edsl_tree_payload(),
            )
        )

        self.assertFalse(response.success)
        self.assertEqual(response.dsl, "")
        self.assertIn("expression generation failed", response.failure_reason)


class FailingPlanner:
    def plan(self, *, node_info, user_query, filtered_env):
        raise RuntimeError("planner exploded")


if __name__ == "__main__":
    unittest.main()
