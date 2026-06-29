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

    def test_node_type_route_prompt_has_narrow_json_contract(self):
        prompt = prompt_manager.render("node_type_route_prompt", query="生成账户ID字段")

        self.assertIn("生成账户ID字段", prompt)
        self.assertIn('"tree_node_type"', prompt)
        self.assertIn('"evidence_terms"', prompt)

    def test_common_node_field_prompt_has_narrow_json_contract(self):
        prompt = prompt_manager.render("common_node_field_prompt", query="生成账户ID字段")

        self.assertIn("生成账户ID字段", prompt)
        self.assertIn('"xml_name_property"', prompt)
        self.assertIn('"reference_logic_area_id_list"', prompt)

    def test_modify_intent_route_prompt_has_narrow_json_contract(self):
        prompt = prompt_manager.render(
            "modify_intent_route_prompt",
            query="改成列表节点",
            current_node_json='{"tree_node_type":"parent"}',
        )

        self.assertIn("改成列表节点", prompt)
        self.assertIn('"intent_type"', prompt)
        self.assertNotIn('"patch_list"', prompt)

    def test_modify_plan_prompt_has_narrow_json_contract(self):
        prompt = prompt_manager.render(
            "modify_plan_prompt",
            query="XML 名称改成 ACCT_ID",
            current_node_json='{"tree_node_type":"simple_leaf"}',
            modify_intent_json='{"intent_type":"set_common_field"}',
        )

        self.assertIn('"common_field_updates"', prompt)
        self.assertIn('"migration_plan"', prompt)
        self.assertNotIn('"patch_list"', prompt)

    def test_node_content_intent_prompt_has_narrow_json_contract(self):
        prompt = prompt_manager.render(
            "node_content_intent_prompt",
            query="任意语义",
            tree_node_type="simple_leaf",
        )

        self.assertIn('"data_type"', prompt)
        self.assertIn('"requires_expression_generation"', prompt)
        self.assertNotIn('"patch"', prompt)


if __name__ == "__main__":
    unittest.main()
