import pytest

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.edsl_expression_parser import EDSLExpressionParser
from agent.expression_generation.expression_type_validation import SimpleDefinition, SimpleExpressionPlan
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue
from agent.planner.models import (
    CallExprPlanNode,
    CompareExprPlanNode,
    ContextPathExprPlanNode,
    FieldAccessExprPlanNode,
    MethodCallExprPlanNode,
    VariableRefExprPlanNode,
)


@pytest.mark.parametrize("plan,expected", [
    (SimpleExpressionPlan(return_expr='if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, "")'),
     'if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, "")'),
    (SimpleExpressionPlan(definitions=[SimpleDefinition(name="charge", expr="fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId))")], return_expr="charge.CHARGE_AMT.long2str()"),
     "def charge: fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId));\ncharge.CHARGE_AMT.long2str()"),
    (SimpleExpressionPlan(definitions=[SimpleDefinition(name="charges", expr="fetch(E_QUERY_CHARGE)")], return_expr="charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT"),
     "def charges: fetch(E_QUERY_CHARGE);\ncharges.find{it.CHARGE_AMT > 0}.CHARGE_AMT"),
])
def test_parses_simple_plan_into_existing_plan_pipeline(plan, expected):
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="$ctx$.address", source_type="context", return_type="logic.Address"),
        TypedRootValue(expr="$ctx$.acct.acctId", source_type="context", return_type="basic.long"),
    ])
    parsed = EDSLExpressionParser(context).parse_plan(plan)
    assert generate_expression(build_ast(parsed)) == expected


def _function_context():
    return TypedExpressionContext(root_values=[
        TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String"),
        TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String"),
        TypedRootValue(expr="Text.wrap", source_type="function", return_type="basic.String"),
    ])


def test_parses_typed_function_root_as_qualified_call():
    parsed = EDSLExpressionParser(_function_context()).parse_plan(
        SimpleExpressionPlan(return_expr='Text.mask($ctx$.name, "x")')
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, CallExprPlanNode)
    assert value.name == "Text.mask"
    assert len(value.args) == 2


def test_parses_nested_native_call_and_result_method_chain():
    parsed = EDSLExpressionParser(_function_context()).parse_plan(
        SimpleExpressionPlan(return_expr='Text.mask(Text.wrap("x"), "y").length()')
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, MethodCallExprPlanNode)
    assert value.name == "length"
    assert isinstance(value.receiver, CallExprPlanNode)
    assert value.receiver.name == "Text.mask"
    assert isinstance(value.receiver.args[0], CallExprPlanNode)
    assert value.receiver.args[0].name == "Text.wrap"


def test_unregistered_qualified_syntax_remains_member_method_call():
    parsed = EDSLExpressionParser(_function_context()).parse_plan(
        SimpleExpressionPlan(return_expr='Other.mask("x")')
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, MethodCallExprPlanNode)
    assert isinstance(value.receiver, VariableRefExprPlanNode)
    assert value.receiver.name == "Other"


def test_parses_native_call_inside_binary_expression():
    parsed = EDSLExpressionParser(_function_context()).parse_plan(
        SimpleExpressionPlan(return_expr='Text.mask($ctx$.name, "x") == "masked"')
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, CompareExprPlanNode)
    assert isinstance(value.left, CallExprPlanNode)
    assert value.left.name == "Text.mask"


def test_accepts_word_logical_operator_and_single_quoted_strings():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="exists", source_type="function", return_type="basic.boolean"),
        TypedRootValue(expr="prep_main", source_type="context", return_type="bo.PrepMain"),
    ])

    parsed = EDSLExpressionParser(context).parse_plan(
        SimpleExpressionPlan(
            return_expr=(
                "if(exists(prep_main) and "
                "prep_main.BEXT_ATTR.RE_BILL_GEN_FLAG == '1', 'Y', 'N')"
            )
        )
    )

    assert generate_expression(build_ast(parsed)) == (
        'if((exists(prep_main) and prep_main.BEXT_ATTR.RE_BILL_GEN_FLAG == "1"), "Y", "N")'
    )


def test_accepts_or_but_does_not_split_operator_text_inside_identifiers():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="brand", source_type="context", return_type="basic.String"),
        TypedRootValue(expr="order", source_type="context", return_type="basic.String"),
    ])

    parsed = EDSLExpressionParser(context).parse_plan(
        SimpleExpressionPlan(return_expr="brand == 'A' or order == 'B'")
    )

    assert generate_expression(build_ast(parsed)) == '(brand == "A" or order == "B")'


@pytest.mark.parametrize("operator", ["+", "-", "*", "/"])
def test_preserves_arithmetic_as_infix_expression(operator):
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="A", source_type="context", return_type="basic.long"),
        TypedRootValue(expr="B", source_type="context", return_type="basic.long"),
    ])

    parsed = EDSLExpressionParser(context).parse_plan(
        SimpleExpressionPlan(return_expr=f"A {operator} B")
    )

    assert generate_expression(build_ast(parsed)) == f"A {operator} B"


def test_parses_exact_iter_as_context_path_even_without_typed_fields():
    parsed = EDSLExpressionParser(TypedExpressionContext()).parse_plan(
        SimpleExpressionPlan(return_expr="$iter$")
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, ContextPathExprPlanNode)
    assert value.path == "$iter$"


def test_parses_registered_iter_field_chain():
    context = TypedExpressionContext(
        root_values=[
            TypedRootValue(
                expr="$iter$",
                source_type="local_context",
                return_type="bo.Customer",
            )
        ]
    )
    parsed = EDSLExpressionParser(context).parse_plan(
        SimpleExpressionPlan(return_expr="$iter$.ID")
    )

    value = parsed.nodes[-1].value
    assert isinstance(value, FieldAccessExprPlanNode)
    assert isinstance(value.receiver, ContextPathExprPlanNode)
    assert value.receiver.path == "$iter$"
    assert value.field == "ID"
