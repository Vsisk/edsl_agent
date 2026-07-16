import unittest

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.nodes import (
    CallNode,
    CompareNode,
    ContextPathNode,
    FieldAccessNode,
    FetchNode,
    FunctionParamNode,
    LiteralNode,
    ProgramNode,
    ReturnNode,
    SelectNode,
)
from agent.expression_generation.ast.validator import (
    AstValidationContext,
    infer_ast_return_type,
    validate_ast,
    validate_ast_with_result,
)
from agent.expression_generation.type_system import (
    TypeDef,
    TypeRef,
    TypeRegistry,
    create_builtin_method_registry,
)
from agent.resource_manager.loader.registry_models import ContextRegistry, ReturnType


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

    def test_context_path_chain_resolves_fields_from_registered_types(self):
        type_registry = TypeRegistry()
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="logic", name="AType"),
                fields={"b": TypeRef(kind="logic", name="BType")},
            )
        )
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="logic", name="BType"),
                fields={"c": TypeRef(kind="extattr", name="CAttr")},
            )
        )
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="extattr", name="CAttr"),
                fields={"d": TypeRef(kind="basic", name="String")},
            )
        )
        context_registry = {
            "$ctx$.a": ContextRegistry(
                resource_id="ctx.a",
                context_name="$ctx$.a",
                return_type=ReturnType(data_type="logic", data_type_name="AType", is_list=False),
                property_type="custom",
                annotation="a",
            )
        }
        ast = ProgramNode(
            type="program",
            body=[
                ReturnNode(
                    type="return",
                    value=ContextPathNode(type="context_path", path="$ctx$.a.b.c.d"),
                )
            ],
        )

        validate_ast(
            ast,
            AstValidationContext(
                context_registry=context_registry,
                type_registry=type_registry,
                method_registry=create_builtin_method_registry(),
            ),
        )

    def test_infer_ast_return_type_returns_final_return_typeref(self):
        type_registry = TypeRegistry()
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="logic", name="Address"),
                fields={"addr1": TypeRef(kind="basic", name="String")},
            )
        )
        ast = build_ast(
            {
                "nodes": [
                    {
                        "type": "return",
                        "value": {
                            "type": "method_call",
                            "receiver": {
                                "type": "field_access",
                                "receiver": {"type": "context_path", "path": "$ctx$.address"},
                                "field": "addr1",
                            },
                            "name": "length",
                            "args": [],
                        },
                    }
                ]
            }
        )

        validation_context = AstValidationContext(
                context_types={"$ctx$.address": TypeRef(kind="logic", name="Address")},
                type_registry=type_registry,
                method_registry=create_builtin_method_registry(),
        )
        result = validate_ast_with_result(ast, validation_context)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.return_type, TypeRef(kind="basic", name="int"))
        self.assertEqual(infer_ast_return_type(ast, validation_context), TypeRef(kind="basic", name="int"))

    def test_exact_iter_root_and_field_resolve_from_context_types(self):
        type_registry = TypeRegistry()
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="bo", name="Customer"),
                fields={"ID": TypeRef(kind="basic", name="long")},
            )
        )
        validation_context = AstValidationContext(
            context_types={"$iter$": TypeRef(kind="bo", name="Customer")},
            type_registry=type_registry,
            method_registry=create_builtin_method_registry(),
        )
        exact = ProgramNode(
            type="program",
            body=[ReturnNode(type="return", value=ContextPathNode(type="context_path", path="$iter$"))],
        )
        field = ProgramNode(
            type="program",
            body=[
                ReturnNode(
                    type="return",
                    value=FieldAccessNode(
                        type="field_access",
                        receiver=ContextPathNode(type="context_path", path="$iter$"),
                        field="ID",
                    ),
                )
            ],
        )

        self.assertEqual(
            infer_ast_return_type(exact, validation_context),
            TypeRef(kind="bo", name="Customer"),
        )
        self.assertEqual(
            infer_ast_return_type(field, validation_context),
            TypeRef(kind="basic", name="long"),
        )

    def test_unregistered_exact_iter_is_unknown_context_path(self):
        ast = ProgramNode(
            type="program",
            body=[ReturnNode(type="return", value=ContextPathNode(type="context_path", path="$iter$"))],
        )

        with self.assertRaisesRegex(ValueError, r"context path not found: \$iter\$"):
            validate_ast(ast, AstValidationContext(context_types={}))

    def test_validate_ast_with_result_reports_error_without_throwing(self):
        ast = ProgramNode(
            type="program",
            body=[
                ReturnNode(
                    type="return",
                    value=FieldAccessNode(
                        type="field_access",
                        receiver=ContextPathNode(type="context_path", path="$ctx$.name"),
                        field="missing",
                    ),
                )
            ],
        )

        result = validate_ast_with_result(
            ast,
            AstValidationContext(
                context_types={"$ctx$.name": TypeRef(kind="basic", name="String")},
                type_registry=TypeRegistry(),
                method_registry=create_builtin_method_registry(),
            ),
        )

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.return_type)
        self.assertEqual(result.errors[0]["error_type"], "AST_VALIDATION_FAILED")

    def test_context_path_chain_rejects_missing_nested_field(self):
        type_registry = TypeRegistry()
        type_registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="logic", name="AType"),
                fields={"b": TypeRef(kind="logic", name="BType")},
            )
        )
        context_registry = {
            "$ctx$.a": ContextRegistry(
                resource_id="ctx.a",
                context_name="$ctx$.a",
                return_type=ReturnType(data_type="logic", data_type_name="AType", is_list=False),
                property_type="custom",
                annotation="a",
            )
        }
        ast = ProgramNode(
            type="program",
            body=[
                ReturnNode(
                    type="return",
                    value=FieldAccessNode(
                        type="field_access",
                        receiver=ContextPathNode(type="context_path", path="$ctx$.a.b"),
                        field="missing",
                    ),
                )
            ],
        )

        with self.assertRaisesRegex(ValueError, "field not found.*missing"):
            validate_ast(
                ast,
                AstValidationContext(
                    context_registry=context_registry,
                    type_registry=type_registry,
                    method_registry=create_builtin_method_registry(),
                ),
            )


if __name__ == "__main__":
    unittest.main()
