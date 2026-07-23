import pytest

from agent.expression_generation.expression_type_validation import SimpleDefinition, SimpleExpressionPlan
from agent.expression_generation.type_system import TypeDef, TypeRef, TypeRegistry, create_builtin_method_registry
from agent.expression_generation.typed_context import TypedExpressionContext, TypedRootValue, TypedVarTemplate
from agent.models import ValueLogicRequest
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    DataTypeEnum,
    DomainRegistry,
    PropertyTerm,
)
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


class IterLoader:
    def __init__(self, tree):
        self.tree = tree
        self.bo = BoRegistry(
            resource_id="bo.customer",
            bo_name="Customer",
            bo_desc="customers",
            property_list=[
                PropertyTerm(
                    field_name="ID",
                    description="customer id",
                    data_type=DataTypeEnum.basic,
                    data_type_name="long",
                )
            ],
        )

    def load_resource(self, *args):
        return LoadedResource(
            context_registry={},
            bo_registry={self.bo.bo_name: self.bo},
            function_registry={},
            edsl_tree=self.tree,
            domain_registry=DomainRegistry(bo_domains=[self.bo.bo_name]),
        )


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
    assert result.return_type.model_dump() == {
        "is_list": False,
        "data_type": "basic",
        "data_type_name": "String",
    }
    assert set(result.debug_info) == {"typed_context", "simple_plan", "parsed_plan", "ast_validation_result", "return_type"}
    assert result.debug_info["ast_validation_result"]["is_valid"] is True
    assert result.debug_info["ast_validation_result"]["return_type"]["kind"] == "basic"
    assert result.debug_info["ast_validation_result"]["return_type"]["name"] == "String"
    assert result.debug_info["return_type"] == {"kind": "basic", "name": "String", "element_type": None, "key_type": None, "value_type": None, "nullable": True}


def test_list_iterator_field_end_to_end_uses_structural_type_and_skill():
    tree = {
        "mapping_content": {
            "node_id": "customers",
            "tree_node_type": "parent_list",
            "data_source": {
                "data_source_type": "sql",
                "sql_query": {"bo_name": "Customer"},
            },
            "children": [
                {
                    "node_id": "customer-id",
                    "tree_node_type": "simple_leaf",
                    "annotation": "客户ID",
                }
            ],
        }
    }

    class IterPlanner:
        def __init__(self):
            self.calls = []

        def plan(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleExpressionPlan(return_expr="$iter$.ID")

    planner = IterPlanner()
    generator = ValueLogicGenerator(
        resource_loader=IterLoader(tree),
        resource_filter_target_generator=Targets(),
        llm_planner=planner,
    )
    request_value = ValueLogicRequest(
        site_id="s",
        project_id="p",
        node_path="$.mapping_content.children[0]",
        node={"node_id": "customer-id", "annotation": "客户ID"},
        query="生成客户ID",
        edsl_tree=tree,
        debug=True,
    )

    result = generator.generate(request_value)

    assert result.expression == "$iter$.ID"
    assert result.return_type.model_dump() == {
        "is_list": False,
        "data_type": "basic",
        "data_type_name": "long",
    }
    typed_context = planner.calls[0]["typed_context"]
    iterator = next(root for root in typed_context.root_values if root.expr == "$iter$")
    assert any(field.access == "$iter$.ID" for field in iterator.fields)
    spec = planner.calls[0]["expression_spec"]
    assert spec.scope_context.inside_parent_list is True
    assert [item.skill_id for item in spec.skill_instructions] == ["list-current-element"]


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
    def fail_validation(*_args, **_kwargs): raise ValueError("invalid ast")
    monkeypatch.setattr("agent.value_logic_generator.validate_ast_with_result", fail_validation)
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


def test_parse_validation_failure_retries_whole_pipeline_and_can_recover():
    context = TypedExpressionContext(root_values=[])

    class RecoveringPlanner:
        def __init__(self):
            self.calls = 0
            self.feedback = []

        def plan(self, **kwargs):
            self.calls += 1
            self.feedback.append(kwargs.get("retry_feedback"))
            if self.calls == 1:
                return SimpleExpressionPlan(
                    definitions=[{"name": "charge", "expr": "fetch_one(E_QUERY_CHARGE, broken)"}],
                    return_expr="charge",
                )
            return SimpleExpressionPlan(return_expr='"ok"')

    planner = RecoveringPlanner()
    generator = ValueLogicGenerator(
        resource_loader=Loader(),
        resource_filter_target_generator=Targets(),
        llm_planner=planner,
        typed_expression_context_builder=Builder(context),
    )

    result = generator.generate(request(debug=True))

    assert result.logic_type == "expression"
    assert result.expression == '"ok"'
    assert planner.calls == 2
    assert planner.feedback[0] is None
    assert planner.feedback[1]["stage"] == "validation"
    assert planner.feedback[1]["error_type"] == "PARSE_FAILED"
    assert "broken" in planner.feedback[1]["message"]


def test_validation_failure_returns_last_result_after_retry_exhaustion():
    context = TypedExpressionContext(root_values=[])
    invalid_plan = SimpleExpressionPlan(
        definitions=[{"name": "charge", "expr": "fetch_one(E_QUERY_CHARGE, broken)"}],
        return_expr="charge",
    )

    class CountingPlanner(Planner):
        def __init__(self):
            super().__init__(invalid_plan)
            self.calls = 0

        def plan(self, **kwargs):
            self.calls += 1
            return super().plan(**kwargs)

    planner = CountingPlanner()
    generator = ValueLogicGenerator(
        resource_loader=Loader(),
        resource_filter_target_generator=Targets(),
        llm_planner=planner,
        typed_expression_context_builder=Builder(context),
        generation_max_attempts=3,
    )

    result = generator.generate(request(debug=True))

    assert result.logic_type == "validation_failed"
    assert result.validation_errors[0]["error_type"] == "PARSE_FAILED"
    assert planner.calls == 3


def test_native_function_call_round_trips_through_ast():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="$ctx$.name", source_type="context", return_type="basic.String"),
        TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String"),
    ])
    expr = 'Text.mask($ctx$.name, "x").length()'

    result, _ = run(SimpleExpressionPlan(return_expr=expr), context)

    assert result.expression == expr


def test_debug_return_type_for_query_variable_method_chain():
    charge = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    registry = TypeRegistry(); registry.register_type(TypeDef(owner_type=charge, fields={"CHARGE_AMT": TypeRef(kind="basic", name="long")}))
    context = TypedExpressionContext(var_templates=[
        TypedVarTemplate(var_name="it", definition_expr="fetch_one(E_QUERY_CHARGE)", return_type="bo.BB_BILL_CHARGE")
    ])

    result, _ = run(
        SimpleExpressionPlan(
            definitions=[SimpleDefinition(name="charge", expr="fetch_one(E_QUERY_CHARGE)")],
            return_expr="charge.CHARGE_AMT.long2str()",
        ),
        context,
        registry,
        debug=True,
    )

    assert result.expression == "def charge: fetch_one(E_QUERY_CHARGE);\ncharge.CHARGE_AMT.long2str()"
    assert result.return_type.model_dump() == {
        "is_list": False,
        "data_type": "basic",
        "data_type_name": "String",
    }
    assert result.debug_info["return_type"]["kind"] == "basic"
    assert result.debug_info["return_type"]["name"] == "String"


def test_value_result_return_type_for_list_return_expression():
    charge = TypeRef(kind="bo", name="BB_BILL_CHARGE")
    registry = TypeRegistry(); registry.register_type(TypeDef(owner_type=charge, fields={"CHARGE_AMT": TypeRef(kind="basic", name="long")}))
    context = TypedExpressionContext(var_templates=[
        TypedVarTemplate(var_name="it", definition_expr="fetch(E_QUERY_CHARGE)", return_type="List<bo.BB_BILL_CHARGE>")
    ])

    result, _ = run(
        SimpleExpressionPlan(
            definitions=[SimpleDefinition(name="charges", expr="fetch(E_QUERY_CHARGE)")],
            return_expr="charges.findAll{it.CHARGE_AMT > 0}",
        ),
        context,
        registry,
    )

    assert result.return_type.model_dump() == {
        "is_list": True,
        "data_type": "bo",
        "data_type_name": "BB_BILL_CHARGE",
    }


def test_value_result_return_type_defaults_to_basic_string_when_static_inference_unknown():
    context = TypedExpressionContext(root_values=[])

    result, _ = run(SimpleExpressionPlan(return_expr="unknownVar"), context)

    assert result.return_type.model_dump() == {
        "is_list": False,
        "data_type": "basic",
        "data_type_name": "String",
    }


def test_unclosed_native_function_call_returns_parse_failed():
    context = TypedExpressionContext(root_values=[
        TypedRootValue(expr="Text.mask", source_type="function", return_type="basic.String"),
    ])

    result, _ = run(SimpleExpressionPlan(return_expr='Text.mask("x"'), context, debug=True)

    assert result.logic_type == "validation_failed"
    assert result.validation_errors[0]["error_type"] == "PARSE_FAILED"
    assert result.debug_info["parsed_plan"] is None
