import unittest

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    FetchNode,
    FunctionParamNode,
    LiteralNode,
    ProgramNode,
    SelectNode,
)
from agent.expression_generation.ast.validator import validate_ast


class ExpressionValidatorTest(unittest.TestCase):
    def test_validate_accepts_basic_program(self):
        ast = build_ast(
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
                                "right": {"type": "literal", "value": 1},
                            },
                        },
                    }
                ]
            }
        )

        self.assertIsNone(validate_ast(ast))

    def test_select_filter_must_be_compare_or_logical(self):
        ast = ProgramNode(
            type="program",
            body=[
                SelectNode(
                    type="select",
                    bo="BB_PREP_SUB",
                    filter=LiteralNode(type="literal", value=True),
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "select filter"):
            validate_ast(ast)

    def test_fetch_params_must_not_repeat_names(self):
        ast = ProgramNode(
            type="program",
            body=[
                FetchNode(
                    type="fetch",
                    name="E_RT_QUERY",
                    params=[
                        FunctionParamNode(name="ID", value=LiteralNode(type="literal", value=1)),
                        FunctionParamNode(name="ID", value=LiteralNode(type="literal", value=2)),
                    ],
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_ast(ast)

    def test_def_name_must_not_be_empty(self):
        ast = build_ast(
            {
                "nodes": [
                    {"type": "def", "name": " ", "value": {"type": "literal", "value": 1}},
                    {"type": "return", "value": {"type": "literal", "value": 1}},
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "def name"):
            validate_ast(ast)

    def test_context_and_variable_names_must_not_be_empty(self):
        ast = ProgramNode(
            type="program",
            body=[
                CompareNode(
                    type="compare",
                    op="==",
                    left=ContextPathNode(type="context_path", path=" "),
                    right=LiteralNode(type="literal", value=1),
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "context path"):
            validate_ast(ast)

    def test_exists_call_requires_one_argument(self):
        ast = ProgramNode(
            type="program",
            body=[
                CallNode(
                    type="call",
                    name="exists",
                    args=[
                        LiteralNode(type="literal", value="left"),
                        LiteralNode(type="literal", value="right"),
                    ],
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "exists"):
            validate_ast(ast)


if __name__ == "__main__":
    unittest.main()
