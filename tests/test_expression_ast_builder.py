import unittest

from pydantic import ValidationError

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    DefNode,
    ProgramNode,
    ReturnNode,
    SelectOneNode,
)
from agent.planner.models import Plan


class ExpressionASTBuilderTest(unittest.TestCase):
    def test_build_ast_converts_plan_container_recursively(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "def",
                        "name": "oid",
                        "value": {
                            "type": "select_one",
                            "bo": "BB_PREP_SUB",
                            "filter": {
                                "type": "compare",
                                "op": "==",
                                "left": {"type": "context_path", "path": "it.PREPARE_ID"},
                                "right": {"type": "context_path", "path": "$ctx$.prepareId"},
                            },
                        },
                    },
                    {"type": "return", "value": {"type": "variable_ref", "name": "oid"}},
                ]
            }
        )

        self.assertIsInstance(ast, ProgramNode)
        self.assertIsInstance(ast.body[0], DefNode)
        self.assertIsInstance(ast.body[0].value, SelectOneNode)
        self.assertIsInstance(ast.body[0].value.filter, CompareNode)
        self.assertIsInstance(ast.body[0].value.filter.right, ContextPathNode)
        self.assertIsInstance(ast.body[1], ReturnNode)

    def test_build_ast_converts_call_node_args_recursively(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "call",
                            "name": "IF",
                            "args": [
                                {
                                    "type": "compare",
                                    "op": "==",
                                    "left": {"type": "context_path", "path": "$ctx$.a.b"},
                                    "right": {"type": "literal", "value": 2},
                                },
                                {"type": "literal", "value": ""},
                                {"type": "context_path", "path": "$ctx$.c.d"},
                            ],
                        },
                    }
                ]
            }
        )

        call = ast.body[0].value
        self.assertIsInstance(call, CallNode)
        self.assertIsInstance(call.args[0], CompareNode)
        self.assertIsInstance(call.args[2], ContextPathNode)

    def test_build_ast_accepts_existing_plan_model(self):
        plan = Plan.model_validate(
            {
                "nodes": [
                    {"type": "return", "value": {"type": "literal", "value": "ok"}},
                ]
            }
        )

        ast = build_ast(plan)

        self.assertIsInstance(ast, ProgramNode)
        self.assertEqual(ast.body[0].value.value, "ok")

    def test_build_ast_rejects_unknown_type(self):
        with self.assertRaises(ValidationError):
            build_ast({"nodes": [{"type": "unknown"}]})

    def test_build_ast_rejects_extra_fields_in_ast_nodes(self):
        with self.assertRaises(ValidationError):
            build_ast(
                {
                    "nodes": [
                        {
                            "type": "return",
                            "value": {
                                "type": "literal",
                                "value": "ok",
                                "reason": "not allowed",
                            },
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
