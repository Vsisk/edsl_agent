import pytest

from agent.expression_generation.expression_type_validation import SimpleDefinition, SimpleExpressionPlan
from agent.expression_generation.type_system import TypeDef, TypeRef, TypeRegistry, create_builtin_method_registry
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue, TypedVarTemplate
from agent.models import ValueLogicRequest
from agent.resource_manager.loader.registry_models import DomainRegistry
from agent.resource_manager.loader.resource_loader import LoadedResource
from agent.value_logic_generator import ValueLogicGenerator


class Loader:
    def load_resource(self, *args):
        return LoadedResource(context_registry={}, bo_registry={}, function_registry={}, edsl_tree={}, domain_registry=DomainRegistry())


class Targets:
    def generate(self, **kwargs): return []


class Builder:
    def __init__(self, context): self.context = context
    def build(self, build_input): return self.context


class Planner:
    def __init__(self, plan): self.result = plan
    def plan(self, **kwargs): return self.result


def request(debug=False):
    return ValueLogicRequest(site_id="s", project_id="p", node_path="$.n", node={"node_id": "n", "name": "n"}, query="q", debug=debug)


def run(plan, context, registry=None, debug=False):
    generator = ValueLogicGenerator(
        resource_loader=Loader(), resource_filter_target_generator=Targets(),
        llm_planner=Planner(plan), typed_expression_context_builder=Builder(context),
        type_registry=registry or TypeRegistry(), method_registry=create_builtin_method_registry(),
    )
    return generator.generate(request(debug)), generator


def test_context_method_end_to_end_with_debug():
    registry = TypeRegistry(); registry.register_type(TypeDef(owner_type=TypeRef(kind="logic", name="Address"), fields={"addr1": TypeRef(kind="basic", name="String")}))
    context = TypedExpressionContext(root_values=[TypedRootValue(expr="$ctx$.address", source_type="context", return_type="logic.Address")])
    expr = 'if($ctx$.address.addr1.length() > 0, $ctx$.address.addr1, "")'
    result, _ = run(SimpleExpressionPlan(return_expr=expr), context, registry, True)
    assert result.expression == expr
    assert set(result.debug_info) == {"typed_context", "simple_plan", "parsed_plan", "ast_validation_result"}
    assert result.debug_info["ast_validation_result"] == {"is_valid": True, "errors": []}


@pytest.mark.parametrize(("name", "fetch", "return_type", "return_expr", "expected"), [
    ("charge", "fetch_one(E_QUERY_CHARGE)", "bo.BB_BILL_CHARGE", "charge.CHARGE_AMT.long2str()", "def charge: fetch_one(E_QUERY_CHARGE);\ncharge.CHARGE_AMT.long2str()"),
    ("charges", "fetch(E_QUERY_CHARGE)", "List<bo.BB_BILL_CHARGE>", "charges.find{it.CHARGE_AMT > 0}.CHARGE_AMT", "def charges: fetch(E_QUERY_CHARGE);\ncharges.find{it.CHARGE_AMT > 0}.CHARGE_AMT"),
])
def test_query_variable_and_list_find_end_to_end(name, fetch, return_type, return_expr, expected):
    charge = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    registry = TypeRegistry(); registry.register_type(TypeDef(owner_type=charge, fields={"CHARGE_AMT": TypeRef(kind="basic", name="long")}))
    context = TypedExpressionContext(var_templates=[TypedVarTemplate(var_name="it", definition_expr=fetch, return_type=return_type)])
    result, _ = run(SimpleExpressionPlan(definitions=[SimpleDefinition(name=name, expr=fetch)], return_expr=return_expr), context, registry)
    assert result.expression == expected


def test_ast_validation_failure_returns_structured_error(monkeypatch):
    context = TypedExpressionContext(root_values=[TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String")])
    def fail_validation(_ast): raise ValueError("invalid ast")
    monkeypatch.setattr("agent.value_logic_generator.validate_ast", fail_validation)
    result, generator = run(SimpleExpressionPlan(return_expr="$ctx$.name"), context, debug=True)
    assert result.logic_type == "validation_failed"
    assert result.validation_errors[0]["error_type"] == "AST_VALIDATION_FAILED"
    assert result.expression is None
    assert result.debug_info["ast_validation_result"]["is_valid"] is False


def test_value_generation_does_not_call_pre_parse_type_validator():
    context = TypedExpressionContext(root_values=[TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String")])
    result, generator = run(SimpleExpressionPlan(return_expr="$ctx$.name"), context)
    class ForbiddenValidator:
        def validate_simple_plan(self, *args): raise AssertionError("pre-parse validator called")
    generator.simple_plan_validator = ForbiddenValidator()
    result = generator.generate(request())
    assert result.logic_type == "expression"


def test_parse_failure_returns_structured_error():
    context = TypedExpressionContext(root_values=[])
    plan = SimpleExpressionPlan(
        definitions=[{"name": "charge", "expr": "fetch_one(E_QUERY_CHARGE, broken)"}],
        return_expr="charge",
    )
    result, _ = run(plan, context, debug=True)
    assert result.logic_type == "validation_failed"
    assert result.validation_errors[0]["error_type"] == "PARSE_FAILED"
    assert result.debug_info["parsed_plan"] is None


def test_native_function_call_round_trips_through_ast():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String"),
        TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String"),
    ])
    expr = 'Text.mask($ctx$.name, "x").length()'

    result, _ = run(SimpleExpressionPlan(return_expr=expr), context)

    assert result.expression == expr


def test_unclosed_native_function_call_returns_parse_failed():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String"),
    ])

    result, _ = run(SimpleExpressionPlan(return_expr='Text.mask("x"'), context, debug=True)

    assert result.logic_type == "validation_failed"
    assert result.validation_errors[0]["error_type"] == "PARSE_FAILED"
    assert result.debug_info["parsed_plan"] is None
