import unittest

from agent.llm.prompt_manager import prompt_manager


class PlannerPromptTest(unittest.TestCase):
    def test_planner_prompt_explains_call_node(self):
        prompt = prompt_manager.render(
            "planner",
            user_requirement="if a equals 2 return empty else c",
            node_info_json="{}",
            resources_json="{}",
            plan_schema_json="{}",
        )

        self.assertIn('"type":"call"', prompt)
        self.assertIn("IF($ctx$.a.b == 2", prompt)
        self.assertIn("generic function call", prompt)

    def test_planner_prompt_explains_exists_call(self):
        prompt = prompt_manager.render(
            "planner",
            user_requirement="check whether prep sub exists",
            node_info_json="{}",
            resources_json="{}",
            plan_schema_json="{}",
        )

        self.assertIn('exists(select(', prompt)
        self.assertIn('"name":"exists"', prompt)


if __name__ == "__main__":
    unittest.main()
