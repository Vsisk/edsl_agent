import pytest

from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.edsl_expression_parser import EDSLExpressionParser
from agent.expression_generation.expression_type_validation import SimpleDefinition, SimpleExpressionPlan
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue


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
