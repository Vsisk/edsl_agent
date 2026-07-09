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
from agent.expression_generation.ast.validator import AstValidationContext, validate_ast
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
