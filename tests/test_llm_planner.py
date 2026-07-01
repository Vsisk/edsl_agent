import unittest
import json

from pydantic import ValidationError

from agent.environment.environment import FilteredEnvironment
from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.planner.llm_planner import LLMPlanner
from agent.planner.models import Plan, ReturnExprPlanNode
from agent.naming_sql_selector.models import NamingSqlSelectionResult, ParamBinding, ParamBindingPlan, SelectedNamingSql


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
                    "planner {{user_requirement}} {{node_info_json}} RESOURCES:"
                    "{{resources_json}} SCHEMA:{{plan_schema_json}}"
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

    def test_plan_exposes_only_authoritative_naming_sql_selection(self):
        client = FakeClient(['{"nodes":[{"type":"fetch","name":"FindCustomer","params":[{"name":"id","value":{"type":"context_path","path":"$ctx$.id"}}]}]}'])
        env = FilteredEnvironment(selected_bos=[Resource(resource_id="bo.1", bo_name="Customer", bo_desc="", property_list=[], naming_sql_list=[Resource(sql_name="FindCustomer", sql_description="secret query", param_list=[]), Resource(sql_name="SiblingSql", sql_description="", param_list=[])])], naming_sql_selection=_selection())
        LLMPlanner(client=client).plan(node_info=_node_info(), user_query="find", filtered_env=env)
        resources = json.loads(client.calls[0]["prompt"].split(" RESOURCES:", 1)[1].split(" SCHEMA:", 1)[0])
        self.assertEqual(resources["naming_sql_selection"], {"bo":"Customer","name":"FindCustomer","bindings":[{"name":"id","source_ref":"$ctx$.id"}]})
        self.assertNotIn("naming_sql", resources["bo"][0]); self.assertNotIn("SiblingSql", client.calls[0]["prompt"]); self.assertNotIn("secret query", client.calls[0]["prompt"])
        for forbidden in ("ns.1", "exact", "confidence", "reason", "fallback_candidates", "rejected_candidates", "sql_command"):
            self.assertNotIn(forbidden, client.calls[0]["prompt"])

    def test_plan_without_selection_omits_selection_summary(self):
        client = FakeClient(['{"nodes":[{"type":"return","value":{"type":"literal","value":null}}]}'])
        LLMPlanner(client=client).plan(node_info=_node_info(), user_query="x", filtered_env=FilteredEnvironment())
        self.assertNotIn("naming_sql_selection", client.calls[0]["prompt"])

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

def _selection():
    return NamingSqlSelectionResult(status="selected", selected_bo="Customer", review_mode="not_required", selected=SelectedNamingSql(naming_sql_id="ns.1", sql_name="FindCustomer", score=1.0, binding_plan=ParamBindingPlan(bindings=[ParamBinding(param_name="id", source_ref="$ctx$.id", confidence=.9, reason="exact")], is_complete=True)))


if __name__ == "__main__":
    unittest.main()
