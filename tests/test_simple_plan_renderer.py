import pytest

from agent.expression_generation.ast.builder import build_simple_ast
from agent.expression_generation.edsl_renderer import EDSLRenderer
from agent.expression_generation.expression_type_validation import SimpleDefinition, SimpleExpressionPlan


def test_renders_definitions_then_verbatim_return_expression():
    plan = SimpleExpressionPlan(
        definitions=[SimpleDefinition(name="charge", expr="fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId))")],
        return_expr="charge.CHARGE_AMT.long2str()",
    )
    assert EDSLRenderer().render_simple_plan(build_simple_ast(plan)) == (
        "def charge: fetch_one(E_QUERY_CHARGE, pair(it.ACCT_ID, $ctx$.acct.acctId));\n"
        "charge.CHARGE_AMT.long2str()"
    )


def test_renders_return_only_and_rejects_bad_definition_name():
    assert EDSLRenderer().render_simple_plan(build_simple_ast(SimpleExpressionPlan(return_expr='"x"'))) == '"x"'
    with pytest.raises(ValueError, match="definition name"):
        build_simple_ast(SimpleExpressionPlan(definitions=[SimpleDefinition(name="bad-name", expr="x")], return_expr="x"))
