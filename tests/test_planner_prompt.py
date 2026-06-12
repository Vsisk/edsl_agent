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

    def test_planner_prompt_requires_class_qualified_function_resource_calls(self):
        prompt = prompt_manager.render(
            "planner",
            user_requirement="mask phone",
            node_info_json="{}",
            resources_json='{"function":[{"name":"DacsDataTrans.CustCallMask"}]}',
            plan_schema_json="{}",
        )

        self.assertIn("Function resources must be called with their provided name", prompt)
        self.assertIn("DacsDataTrans.CustCallMask", prompt)

    def test_resource_filter_target_prompt_explains_root_context_domain(self):
        prompt = prompt_manager.render(
            "resource_filter_target",
            query="使用上下文 bill_id",
            ctx_domains='["bill_id"]',
            bo_domains="[]",
            func_domains="[]",
            namingsql_domains="[]",
            resource_count_summary="{}",
        )

        self.assertIn("$ctx$.xxx", prompt)
        self.assertIn("domain=xxx", prompt)
        self.assertIn("source_type=context", prompt)


if __name__ == "__main__":
    unittest.main()
