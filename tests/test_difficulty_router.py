import unittest

from agent.llm.prompt_manager import prompt_manager
from agent.models import NodeDef
from agent.planner.difficulty_router import LLMDifficultyRouter


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

    def test_context_only_decision_returns_true(self):
        client = FakeClient('{"decision":"context_only","reason":"direct context assignment"}')

        result = LLMDifficultyRouter(client=client).can_plan_with_context_only(
            node_info=_node_info(),
            user_query="directly assign from context",
        )

        self.assertTrue(result)
        self.assertIn("directly assign from context", client.calls[0]["prompt"])
        self.assertIn('"node_name":"Name"', client.calls[0]["prompt"])

    def test_resource_filter_decision_returns_false(self):
        client = FakeClient('{"decision":"resource_filter","reason":"needs table lookup"}')

        result = LLMDifficultyRouter(client=client).can_plan_with_context_only(
            node_info=_node_info(),
            user_query="lookup from table",
        )

        self.assertFalse(result)

    def test_unusable_client_returns_false_without_llm_call(self):
        client = FakeClient('{"decision":"context_only"}')
        client.is_usable = False

        result = LLMDifficultyRouter(client=client).can_plan_with_context_only(
            node_info=_node_info(),
            user_query="directly assign from context",
        )

        self.assertFalse(result)
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
