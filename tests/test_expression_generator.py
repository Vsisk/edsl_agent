import unittest

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import (
    generate_expression,
    inject_expression_comment,
)
from agent.expression_generation.ast.nodes import LiteralNode


class ExpressionGeneratorTest(unittest.TestCase):
    def test_inject_expression_comment_as_line_comment(self):
        self.assertEqual(
            inject_expression_comment("value.FIELD", "selected field"),
            "// selected field\nvalue.FIELD",
        )

    def test_inject_expression_comment_as_block_comment(self):
        self.assertEqual(
            inject_expression_comment("value.FIELD", "selected\nfield", style="block"),
            "/* selected\nfield */\nvalue.FIELD",
        )

    def test_inject_expression_comment_rejects_invalid_style(self):
        with self.assertRaises(ValueError):
            inject_expression_comment("value.FIELD", "note", style="python")

    def test_generate_program_renders_comment_nodes(self):
        ast = build_ast(
            {
                "nodes": [
                    {"type": "comment", "placement": "single", "text": "load source"},
                    {
                        "type": "def",
                        "name": "value",
                        "value": {"type": "fetch_one", "name": "E_QUERY", "params": []},
                    },
                    {"type": "comment", "placement": "inline", "text": "return selected field"},
                    {"type": "return", "value": {"type": "variable_ref", "name": "value"}},
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "/* load source */\ndef value = fetch_one(E_QUERY);\nvalue // return selected field",
        )

    def test_generate_program_renders_multiline_comment_node_as_block(self):
        ast = build_ast(
            {
                "nodes": [
                    {"type": "comment", "placement": "single", "text": "load\nsource"},
                    {"type": "return", "value": {"type": "literal", "value": "ok"}},
                ]
            }
        )

        self.assertEqual(generate_expression(ast), '/* load\nsource */\n"ok"')

    def test_generate_program_allows_comments_between_def_nodes(self):
        ast = build_ast(
            {
                "nodes": [
                    {"type": "comment", "placement": "single", "text": "load primary record"},
                    {
                        "type": "def",
                        "name": "primary",
                        "value": {"type": "fetch_one", "name": "E_QUERY_PRIMARY", "params": []},
                    },
                    {"type": "comment", "placement": "single", "text": "load backup record"},
                    {
                        "type": "def",
                        "name": "backup",
                        "value": {"type": "fetch_one", "name": "E_QUERY_BACKUP", "params": []},
                    },
                    {"type": "comment", "placement": "inline", "text": "prefer primary"},
                    {
                        "type": "return",
                        "value": {
                            "type": "call",
                            "name": "if",
                            "args": [
                                {"type": "context_path", "path": "$ctx$.usePrimary"},
                                {"type": "variable_ref", "name": "primary"},
                                {"type": "variable_ref", "name": "backup"},
                            ],
                        },
                    },
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "/* load primary record */\n"
            "def primary = fetch_one(E_QUERY_PRIMARY);\n"
            "/* load backup record */\n"
            "def backup = fetch_one(E_QUERY_BACKUP);\n"
            "if($ctx$.usePrimary, primary, backup) // prefer primary",
        )

    def test_generate_literals(self):
        self.assertEqual(generate_expression(LiteralNode(type="literal", value="abc")), '"abc"')
        self.assertEqual(generate_expression(LiteralNode(type="literal", value=123)), "123")
        self.assertEqual(generate_expression(LiteralNode(type="literal", value=True)), "true")
        self.assertEqual(generate_expression(LiteralNode(type="literal", value=False)), "false")
        self.assertEqual(generate_expression(LiteralNode(type="literal", value=None)), "null")
        self.assertEqual(generate_expression(LiteralNode(type="literal", value='a"b')), '"a\\"b"')

    def test_generate_program_with_def_and_return_value_without_return_keyword(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "def",
                        "name": "oid",
                        "value": {
                            "type": "fetch_one",
                            "name": "E_RT_QUERY_BY_OFFERINGID",
                            "params": [
                                {
                                    "name": "OFFERING_ID",
                                    "value": {"type": "context_path", "path": "$ctx$.offeringId"},
                                }
                            ],
                        },
                    },
                    {"type": "return", "value": {"type": "variable_ref", "name": "oid"}},
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "def oid = fetch_one(E_RT_QUERY_BY_OFFERINGID, pair(it.OFFERING_ID, $ctx$.offeringId));\noid",
        )

    def test_generate_select_compare_and_logical_with_stable_parentheses(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "select",
                            "bo": "BB_PREP_SUB",
                            "filter": {
                                "type": "logical",
                                "op": "and",
                                "items": [
                                    {
                                        "type": "compare",
                                        "op": "==",
                                        "left": {"type": "context_path", "path": "it.A"},
                                        "right": {"type": "literal", "value": 1},
                                    },
                                    {
                                        "type": "compare",
                                        "op": "!=",
                                        "left": {"type": "context_path", "path": "it.B"},
                                        "right": {"type": "literal", "value": 2},
                                    },
                                ],
                            },
                        },
                    }
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "select(BB_PREP_SUB, (it.A == 1 and it.B != 2))",
        )

    def test_generate_fetch_without_params_uses_no_trailing_comma(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {"type": "fetch", "name": "E_RT_QUERY_ALL", "params": []},
                    }
                ]
            }
        )

        self.assertEqual(generate_expression(ast), "fetch(E_RT_QUERY_ALL)")

    def test_function_param_keeps_existing_prefix(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "fetch",
                            "name": "E_RT_QUERY_BY_CTX",
                            "params": [
                                {
                                    "name": "$ctx$.OFFERING_ID",
                                    "value": {"type": "variable_ref", "name": "oid"},
                                }
                            ],
                        },
                    }
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "fetch(E_RT_QUERY_BY_CTX, pair($ctx$.OFFERING_ID, oid))",
        )

    def test_generate_nested_call_expression(self):
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

        self.assertEqual(
            generate_expression(ast),
            'IF($ctx$.a.b == 2, "", $ctx$.c.d)',
        )

    def test_generate_exists_call_for_bo_list(self):
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "call",
                            "name": "exists",
                            "args": [
                                {
                                    "type": "select",
                                    "bo": "BB_PREP_SUB",
                                    "filter": {
                                        "type": "compare",
                                        "op": "==",
                                        "left": {"type": "context_path", "path": "it.ID"},
                                        "right": {"type": "context_path", "path": "$ctx$.id"},
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        )

        self.assertEqual(
            generate_expression(ast),
            "exists(select(BB_PREP_SUB, it.ID == $ctx$.id))",
        )


if __name__ == "__main__":
    unittest.main()
