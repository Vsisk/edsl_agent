import unittest

from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.planner.difficulty_router import LLMDifficultyRouter, ResourceRoute


class FakeSettings:
    def model_for(self, llm_name: str) -> str:
        return f"{llm_name}-model"


class FakeClient:
    is_usable = True

    def __init__(self, content: str):
        self.content = content
        self.calls = []
        self.settings = FakeSettings()

    def complete(self, **payload):
        self.calls.append(payload)
        return self.content


class LLMDifficultyRouterTest(unittest.TestCase):
    def setUp(self):
        self.original_prompts = prompt_manager._prompts
        prompt_manager._prompts = {
            "difficulty_router": {
                "zh": "route {{user_requirement}} {{node_info_json}}",
            },
        }

    def tearDown(self):
        prompt_manager._prompts = self.original_prompts

    def test_context_only_decision_disables_bo_and_function(self):
        client = FakeClient('{"decision":"context_only","reason":"direct context assignment"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="directly assign from context",
        )

        self.assertEqual(result, ResourceRoute(use_bo=False, use_function=False))
        self.assertIn("directly assign from context", client.calls[0]["prompt"])
        self.assertIn('"node_name":"Name"', client.calls[0]["prompt"])

    def test_bo_only_decision_enables_bo_without_function(self):
        client = FakeClient('{"decision":"bo_only","reason":"needs table lookup"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="lookup from table",
        )

        self.assertEqual(result, ResourceRoute(use_bo=True, use_function=False))

    def test_function_only_decision_enables_function_without_bo(self):
        client = FakeClient('{"required_resources":["function","context"],"reason":"needs function"}')

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="mask phone",
        )

        self.assertEqual(result, ResourceRoute(use_bo=False, use_function=True))

    def test_unusable_client_uses_conservative_full_route_without_llm_call(self):
        client = FakeClient('{"decision":"context_only"}')
        client.is_usable = False

        result = LLMDifficultyRouter(client=client).route_resources(
            node_info=_node_info(),
            user_query="directly assign from context",
        )

        self.assertEqual(result, ResourceRoute(use_bo=True, use_function=True))
        self.assertEqual(client.calls, [])


def _node_info() -> NodeDef:
    return NodeDef(
        node_id="node.1",
        node_path="$.mapping_content.children[0]",
        node_name="Name",
        description="desc",
    )


if __name__ == "__main__":
    unittest.main()
