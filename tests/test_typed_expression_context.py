from agent.context_manager.models import NamingSqlCandidate
from agent.environment.environment import FilteredEnvironment
from agent.expression_generation.type_system import (
    TypeDef,
    TypeRef,
    TypeRegistry,
    create_builtin_method_registry,
)
from agent.expression_generation.typed_context import (
    TypedExpressionContextBuildInput,
    TypedExpressionContextBuilder,
)
from agent.models import NodeDef
from agent.naming_sql_selector.models import NamingSqlSelectResponse
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    DataTypeEnum,
    DomainRegistry,
    PropertyTerm,
    ReturnType,
)
from agent.resource_manager.loader.resource_loader import LoadedResource


def loaded_resource(
    *,
    contexts: list[ContextRegistry] | None = None,
    bos: list[BoRegistry] | None = None,
) -> LoadedResource:
    contexts = contexts or []
    bos = bos or []
    return LoadedResource(
        context_registry={item.context_name: item for item in contexts},
        bo_registry={item.bo_name: item for item in bos},
        function_registry={},
        edsl_tree={},
        domain_registry=DomainRegistry(),
    )


def build_input(
    *,
    filtered_env: FilteredEnvironment,
    loaded: LoadedResource,
    type_registry: TypeRegistry | None = None,
    max_items: int = 80,
) -> TypedExpressionContextBuildInput:
    return TypedExpressionContextBuildInput(
        query="use address and charge amount",
        node=NodeDef(node_id="n1", node_path="$.n1", node_name="CHARGE_AMT"),
        filtered_env=filtered_env,
        loaded_resource=loaded,
        type_registry=type_registry or TypeRegistry(),
        method_registry=create_builtin_method_registry(),
        max_items=max_items,
    )


def charge_bo() -> BoRegistry:
    return BoRegistry(
        resource_id="bo.charge",
        bo_name="BB_BILL_CHARGE",
        bo_desc="bill charge",
        property_list=[
            PropertyTerm(
                field_name="CHARGE_AMT",
                description="charge amount",
                data_type=DataTypeEnum.basic,
                data_type_name="long",
            )
        ],
    )


def test_builder_expands_context_object_to_basic_field_with_methods():
    address_context = ContextRegistry(
        resource_id="ctx.address",
        context_name="$ctx$.address",
        return_type=ReturnType(data_type="logic", data_type_name="Address", is_list=False),
        property_type="system",
        annotation="billing address",
    )
    registry = TypeRegistry()
    registry.register_type(
        TypeDef(
            owner_type=TypeRef(kind="logic", name="Address"),
            fields={"addr1": TypeRef(kind="basic", name="String")},
        )
    )
    context = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[address_context]),
            loaded=loaded_resource(contexts=[address_context]),
            type_registry=registry,
        )
    )

    assert context.root_values[0].expr == "$ctx$.address"
    addr1 = next(field for field in context.root_values[0].fields if field.access == "$ctx$.address.addr1")
    assert addr1.return_type == "basic.String"
    assert "length(): basic.int" in addr1.methods
    assert "dateValue(basic.String format): basic.Date" in addr1.methods


def test_builder_uses_it_for_naming_sql_owning_bo_fields():
    bo = charge_bo()
    candidate = NamingSqlCandidate(
        candidate_id="candidate.charge",
        bo_name=bo.bo_name,
        naming_sql_id="E_QUERY_CHARGE",
        naming_sql_name="E_QUERY_CHARGE",
        return_type={"data_type": "bo", "data_type_name": bo.bo_name, "is_list": False},
        source="resource_registry",
        rank=0,
    )
    selection = NamingSqlSelectResponse(success=True, candidates=[candidate])
    context = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_bos=[bo], naming_sql_selection=selection),
            loaded=loaded_resource(bos=[bo]),
        )
    )

    template = context.var_templates[0]
    assert template.var_name == "it"
    assert template.return_type == "bo.BB_BILL_CHARGE"
    charge_amount = next(field for field in template.available_fields if field.access == "it.CHARGE_AMT")
    assert charge_amount.return_type == "basic.long"
    assert charge_amount.methods == ["long2str(): basic.String"]


def test_builder_warns_and_skips_context_without_return_type():
    context = ContextRegistry.model_construct(
        resource_id="ctx.invalid",
        context_name="$ctx$.invalid",
        return_type=None,
        property_type="system",
        annotation="invalid",
        tag=[],
    )

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[context]),
            loaded=loaded_resource(contexts=[context]),
        )
    )

    assert result.root_values == []
    assert result.warnings == ["missing return_type for context $ctx$.invalid"]

