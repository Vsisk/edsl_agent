import unittest

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.planner.llm_planner import LLMPlanner
from agent.planner.models import Plan, ReturnExprPlanNode


class FakeSettings:
    def model_for(self, llm_name: str) -> str:
        return f"{llm_name}-model"


class FakeClient:
    is_usable = True

    def __init__(self, contents: list[str]):
        self.contents = list(contents)
        self.calls = []
        self.settings = FakeSettings()

    def complete(self, **payload):
        self.calls.append(payload)
        return self.contents.pop(0)


class Resource:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class LLMPlannerTest(unittest.TestCase):
    def setUp(self):
        self.original_prompts = prompt_manager._prompts
        prompt_manager._prompts = {
            "planner": {
                "zh": (
                    "planner {{user_requirement}} {{node_info_json}} "
                    "{{resources_json}} {{plan_schema_json}}"
                )
            },
            "planner_repair": {
                "zh": (
                    "repair {{user_requirement}} {{node_info_json}} "
                    "{{resources_json}} {{plan_schema_json}} "
                    "{{invalid_plan_json}} {{error_message}}"
                )
            },
        }

    def tearDown(self):
        prompt_manager._prompts = self.original_prompts

    def test_plan_returns_validated_plan_from_llm_json(self):
        client = FakeClient(
            [
                '{"nodes":[{"type":"return","value":{"type":"context_path","path":"$ctx$.prepareId"}}]}',
            ]
        )

        plan = LLMPlanner(client=client).plan(
            node_info=_node_info(),
            user_query="return prepare id",
            filtered_env=FilteredEnvironment(
                selected_global_contexts=[
                    Resource(
                        resource_id="ctx.1",
                        context_name="$ctx$.prepareId",
                        annotation="prepare id",
                        return_type=Resource(data_type_name="String"),
                    )
                ],
            ),
        )

        self.assertIsInstance(plan, Plan)
        self.assertIsInstance(plan.nodes[0], ReturnExprPlanNode)
        self.assertIn("$ctx$.prepareId", client.calls[0]["prompt"])

    def test_plan_exposes_function_resource_name_as_class_qualified_call_name(self):
        client = FakeClient(
            [
                '{"nodes":[{"type":"return","value":{"type":"call","name":"DacsDataTrans.CustCallMask","args":[{"type":"context_path","path":"$ctx$.phone"}]}}]}',
            ]
        )

        LLMPlanner(client=client).plan(
            node_info=_node_info(),
            user_query="mask phone",
            filtered_env=FilteredEnvironment(
                selected_functions=[
                    Resource(
                        resource_id="func.1",
                        func_name="CustCallMask",
                        func_class="DacsDataTrans",
                        func_desc="mask customer call number",
                        param_list=[Resource(param_name="phone", data_type_name="String")],
                        return_type=Resource(data_type_name="String"),
                    )
                ],
            ),
        )

        self.assertIn('"name":"DacsDataTrans.CustCallMask"', client.calls[0]["prompt"])
        self.assertIn('"class":"DacsDataTrans"', client.calls[0]["prompt"])

    def test_plan_repairs_once_when_initial_output_fails_pydantic_validation(self):
        client = FakeClient(
            [
                '{"nodes":[]}',
                '{"nodes":[{"type":"return","value":{"type":"literal","value":null}}]}',
            ]
        )

        plan = LLMPlanner(client=client).plan(
            node_info=_node_info(),
            user_query="return null",
            filtered_env=FilteredEnvironment(),
        )

        self.assertEqual(len(client.calls), 2)
        self.assertIsNone(plan.nodes[0].value.value)
        self.assertIn("repair", client.calls[1]["prompt"])

    def test_plan_raises_when_repair_still_fails(self):
        client = FakeClient(['{"nodes":[]}', '{"nodes":[]}'])

        with self.assertRaises(ValidationError):
            LLMPlanner(client=client).plan(
                node_info=_node_info(),
                user_query="return null",
                filtered_env=FilteredEnvironment(),
            )

    def test_plan_raises_when_planner_is_not_usable(self):
        client = FakeClient([])
        client.is_usable = False

        with self.assertRaisesRegex(RuntimeError, "LLM planner is not usable"):
            LLMPlanner(client=client).plan(
                node_info=_node_info(),
                user_query="return null",
                filtered_env=FilteredEnvironment(),
            )


def _node_info() -> NodeDef:
    return NodeDef(
        node_id="node.1",
        node_path="/Root/Node",
        node_name="Node",
        description="Node description",
    )


if __name__ == "__main__":
    unittest.main()
