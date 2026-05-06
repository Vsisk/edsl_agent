import unittest

from pydantic import TypeAdapter, ValidationError

from agent.planner.models import (
    CompareExprPlanNode,
    DefExprPlanNode,
    EXPR_PLAN_NODE_SCHEMA,
    ExprPlanNode,
    FetchExprPlanNode,
    LiteralExprPlanNode,
    LogicalExprPlanNode,
    ReturnExprPlanNode,
    SelectExprPlanNode,
    SelectOneExprPlanNode,
)


class ExprPlanNodeModelsTest(unittest.TestCase):
    def test_expr_plan_node_accepts_recursive_composition(self):
        node = TypeAdapter(ExprPlanNode).validate_python(
            {
                "type": "return",
                "value": {
                    "type": "compare",
                    "op": "==",
                    "left": {"type": "context_path", "path": "$ctx$.billStatement.prepareId"},
                    "right": {"type": "literal", "value": "P1"},
                },
            }
        )

        self.assertIsInstance(node, ReturnExprPlanNode)
        self.assertIsInstance(node.value, CompareExprPlanNode)

    def test_models_reject_unneeded_extra_fields(self):
        with self.assertRaises(ValidationError):
            LiteralExprPlanNode(type="literal", value="abc", reason="not needed")

    def test_logical_items_require_at_least_two_expressions(self):
        with self.assertRaises(ValidationError):
            LogicalExprPlanNode(type="logical", op="and", items=[LiteralExprPlanNode(type="literal", value=True)])

    def test_fetch_params_can_be_empty_but_param_value_is_recursive_node(self):
        empty_fetch = FetchExprPlanNode(type="fetch", name="E_RT_QUERY_BY_OFFERINGID", params=[])
        self.assertEqual(empty_fetch.params, [])

        fetch = FetchExprPlanNode.model_validate(
            {
                "type": "fetch",
                "name": "E_RT_QUERY_BY_OFFERINGID",
                "params": [
                    {
                        "name": "OFFERING_ID",
                        "value": {"type": "variable_ref", "name": "oid"},
                    }
                ],
            }
        )
        self.assertEqual(fetch.params[0].value.name, "oid")

    def test_json_schema_is_exportable_from_expr_plan_node(self):
        schema = TypeAdapter(ExprPlanNode).json_schema()

        self.assertIn("$defs", schema)
        self.assertIn("oneOf", schema)
        self.assertIn("CompareExprPlanNode", schema["$defs"])
        self.assertEqual(
            schema["$defs"]["CompareExprPlanNode"]["properties"]["op"]["enum"],
            ["==", "!=", ">", ">=", "<", "<="],
        )
        self.assertEqual(
            schema["$defs"]["LogicalExprPlanNode"]["properties"]["items"]["minItems"],
            2,
        )

    def test_required_fields_are_minimal_per_node(self):
        self.assertEqual(
            DefExprPlanNode.model_json_schema()["$defs"]["DefExprPlanNode"]["required"],
            ["type", "name", "value"],
        )
        self.assertEqual(
            SelectExprPlanNode.model_json_schema()["$defs"]["SelectExprPlanNode"]["required"],
            ["type", "bo", "filter"],
        )
        self.assertEqual(
            SelectOneExprPlanNode.model_json_schema()["$defs"]["SelectOneExprPlanNode"]["required"],
            ["type", "bo", "filter"],
        )

    def test_planner_models_export_schema_dict(self):
        self.assertEqual(EXPR_PLAN_NODE_SCHEMA, TypeAdapter(ExprPlanNode).json_schema())


if __name__ == "__main__":
    unittest.main()
