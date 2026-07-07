from agent.expression_generation.ast.builder import build_ast
from agent.expression_generation.ast.generator import generate_expression
from agent.expression_generation.ast.validator import validate_ast
from agent.planner.models import Plan


def test_builds_validates_and_renders_member_method_and_lambda_nodes():
    plan = Plan.model_validate({"nodes": [{"type": "return", "value": {
        "type": "field_access", "field": "CHARGE_AMT", "receiver": {
            "type": "method_call", "name": "find", "args": [],
            "receiver": {"type": "variable_ref", "name": "charges"},
            "lambda_expr": {"type": "compare", "op": ">", "left": {
                "type": "field_access", "receiver": {"type": "variable_ref", "name": "it"},
                "field": "CHARGE_AMT"}, "right": {"type": "literal", "value": 0}}
        }
    }}]})
    ast = build_ast(plan)
    validate_ast(ast)
    assert generate_expression(ast) == "charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT"
