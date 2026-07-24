import pytest
from pydantic import ValidationError

from agent.expression_generation.expression_type_validation import (
    ExpressionValidationInput,
    MethodChainValidator,
    SimpleDefinition,
    SimpleExpressionPlan,
)
from agent.expression_generation.type_system import TypeDef, TypeRef, TypeRegistry, create_builtin_method_registry
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue, TypedVarTemplate


STRING = TypeRef(kind="basic", name="String")
INT = TypeRef(kind="basic", name="int")
LONG = TypeRef(kind="basic", name="long")
CHARGE = TypeRef(kind="bo", name="BB_BILL_CHARGE")
CHARGES = TypeRef(kind="list", element_type=CHARGE)


def validator() -> MethodChainValidator:
    types = TypeRegistry()
    types.register_type(TypeDef(owner_type=TypeRef(kind="logic", name="Address"), fields={"addr1": STRING}))
    types.register_type(TypeDef(owner_type=CHARGE, fields={"CHARGE_AMT": LONG}))
    context = TypedExpressionContext(
        root_values=[
            TypedRootValue(expr="$ctx$.address", source_type="context", return_type="logic.Address"),
            TypedRootValue(expr="$ctx$.billStatement.fromDate", source_type="context", return_type="basic.String"),
        ],
        var_templates=[
            TypedVarTemplate(var_name="it", definition_expr="fetch_one(E_QUERY_CHARGE)", return_type="bo.BB_BILL_CHARGE"),
            TypedVarTemplate(var_name="it", definition_expr="fetch(E_QUERY_CHARGE)", return_type="List<bo.BB_BILL_CHARGE>"),
        ],
    )
    return MethodChainValidator(ExpressionValidationInput(
        typed_context=context, type_registry=types, method_registry=create_builtin_method_registry()
    ))


def plan(expr: str, definitions=None) -> SimpleExpressionPlan:
    return SimpleExpressionPlan(definitions=definitions or [], return_expr=expr)


def test_simple_plan_rejects_target_return_type_from_planner():
    with pytest.raises(ValidationError):
        SimpleExpressionPlan.model_validate({
            "definitions": [], "return_expr": '"x"',
            "target_return_type": {"kind": "basic", "name": "String"},
        })


@pytest.mark.parametrize(("expr", "expected"), [
    ("$ctx$.address.addr1.length()", INT),
    ('if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, "")', STRING),
    ('$ctx$.billStatement.fromDate.dateValue("yyyy.MM.dd").addDays(1).toString("yyyy.MM.dd")', STRING),
])
def test_resolves_required_context_expressions(expr, expected):
    result = validator().validate(plan(expr))
    assert result.errors == []
    assert result.return_type == expected


def test_resolves_word_logical_operator_and_single_quoted_strings():
    expr = (
        "if($ctx$.address.addr1.length() > 0 and "
        "$ctx$.billStatement.fromDate == '2026-07-24', 'Y', 'N')"
    )

    result = validator().validate(plan(expr))

    assert result.errors == []
    assert result.return_type == STRING


def test_resolves_definition_fetch_one_then_method_chain():
    result = validator().validate(plan("charge.CHARGE_AMT.long2str()", [SimpleDefinition(name="charge", expr="fetch_one(E_QUERY_CHARGE)")]))
    assert result.errors == [] and result.return_type == STRING
    assert result.definition_types["charge"] == CHARGE


def test_resolves_list_lambda_and_continues_field_chain():
    result = validator().validate(plan("charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT", [SimpleDefinition(name="charges", expr="fetch(E_QUERY_CHARGE)")]))
    assert result.errors == [] and result.return_type == LONG


@pytest.mark.parametrize(("expr", "error_type"), [
    ("$ctx$.address.addr1.addDays(1)", "METHOD_NOT_FOUND"),
    ("$ctx$.address.addr1.xxx", "FIELD_ACCESS_ON_BASIC_TYPE"),
])
def test_reports_required_chain_errors(expr, error_type):
    result = validator().validate(plan(expr))
    assert result.errors[0].error_type == error_type
    assert result.errors[0].expr == expr


def test_reports_direct_list_field_access():
    result = validator().validate(plan("charges.CHARGE_AMT", [SimpleDefinition(name="charges", expr="fetch(E_QUERY_CHARGE)")]))
    assert result.errors[-1].error_type == "LIST_FIELD_ACCESS_WITHOUT_ELEMENT_METHOD"


def test_reports_if_branch_type_mismatch():
    expr = 'if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, 0)'
    result = validator().validate(plan(expr))
    assert result.errors[-1].error_type == "IF_BRANCH_TYPE_MISMATCH"


@pytest.mark.parametrize(("expr", "error_type"), [
    ("mystery()", "UNKNOWN_ROOT"),
    ("$ctx$.missing.value", "UNKNOWN_CONTEXT_PATH"),
    ("missing.FIELD", "UNKNOWN_VARIABLE"),
    ("$ctx$.address.missing", "FIELD_NOT_FOUND"),
    ("$ctx$.address.addr1.substr(1)", "METHOD_ARG_COUNT_MISMATCH"),
    ('$ctx$.address.addr1.substr("bad", 1)', "METHOD_ARG_TYPE_MISMATCH"),
    ('if("not boolean", "a", "b")', "IF_CONDITION_NOT_BOOLEAN"),
])
def test_reports_structured_validation_error_categories(expr, error_type):
    result = validator().validate(plan(expr))
    assert error_type in [error.error_type for error in result.errors]
    error = next(error for error in result.errors if error.error_type == error_type)
    assert error.expr == expr and error.message


def test_reports_non_boolean_lambda_expression():
    result = validator().validate(plan(
        "charges.find{it.CHARGE_AMT}.CHARGE_AMT",
        [SimpleDefinition(name="charges", expr="fetch(E_QUERY_CHARGE)")],
    ))
    assert "LAMBDA_EXPR_NOT_BOOLEAN" in [error.error_type for error in result.errors]


def test_reports_lambda_it_type_not_found():
    current = validator()
    current.input.typed_context.var_templates.append(
        TypedVarTemplate(var_name="it", definition_expr="fetch(BAD)", return_type="unknown")
    )
    result = current.validate(plan(
        "items.find{true}", [SimpleDefinition(name="items", expr="fetch(BAD)")]
    ))
    assert "LAMBDA_IT_TYPE_NOT_FOUND" in [error.error_type for error in result.errors]
