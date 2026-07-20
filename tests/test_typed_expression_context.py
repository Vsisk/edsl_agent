from agent.context_manager.models import NamingSqlCandidate
from agent.context_pack.models import ContextPack
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
from agent.naming_sql_selector.models import NamingSqlSelectResponse, SelectionMode
from agent.resource_manager.loader.registry_models import (
    BoRegistry,
    ContextRegistry,
    DataTypeEnum,
    DomainRegistry,
    PropertyTerm,
    ReturnType,
    LocalContextRegistry,
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
        context_pack=ContextPack(status="complete", request_summary={"query": "use address"},
                                 current_node={"node_id": "n1"}),
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
    assert "length(): basic.int" in next(item.methods for item in context.method_catalog if item.owner_type == "basic.String")
    assert "dateValue(basic.String format): basic.Date" in next(item.methods for item in context.method_catalog if item.owner_type == "basic.String")


def test_builder_registers_iterator_bo_and_expands_fields_without_selected_bo():
    bo = charge_bo()
    iterator = LocalContextRegistry(
        resource_id="local.iter",
        context_name="$iter$",
        return_type=ReturnType(
            data_type="bo",
            data_type_name=bo.bo_name,
            is_list=False,
        ),
        property_type="iter",
        source_path="$.charges.data_source",
    )

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(visible_local_context=[iterator]),
            loaded=loaded_resource(bos=[bo]),
        )
    )

    root = next(item for item in result.root_values if item.expr == "$iter$")
    assert root.return_type == "bo.BB_BILL_CHARGE"
    assert any(
        field.access == "$iter$.CHARGE_AMT"
        and field.return_type == "basic.long"
        for field in root.fields
    )


def test_builder_expands_context_logic_and_extattr_data_type_defs():
    extattr_context = ContextRegistry(
        resource_id="ctx.a.b",
        context_name="$ctx$.a.b",
        return_type=ReturnType(data_type="extattr", data_type_name="Aextattr", is_list=False),
        property_type="custom",
        annotation="external extattr reference",
    )
    loaded = loaded_resource(contexts=[extattr_context])
    loaded.type_defs.extend(
        [
            TypeDef(
                owner_type=TypeRef(kind="extattr", name="Aextattr"),
                fields={"a_extattr_id": TypeRef(kind="basic", name="String")},
            )
        ]
    )

    context = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[extattr_context]),
            loaded=loaded,
        )
    )

    root = context.root_values[0]
    assert root.expr == "$ctx$.a.b"
    ext_id = next(field for field in root.fields if field.access == "$ctx$.a.b.a_extattr_id")
    assert ext_id.return_type == "basic.String"
    assert "length(): basic.int" in next(item.methods for item in context.method_catalog if item.owner_type == "basic.String")


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
    selection = NamingSqlSelectResponse(success=True, selection_mode=SelectionMode.DETERMINISTIC_FALLBACK,
                                        candidates=[candidate])
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
    assert next(item.methods for item in context.method_catalog if item.owner_type == "basic.long") == ["long2str(): basic.String"]


def test_builder_binds_naming_sql_condition_from_owning_bo_field():
    bo = charge_bo()
    context_value = ContextRegistry(
        resource_id="ctx.charge_amount",
        context_name="$ctx$.chargeAmt",
        return_type=ReturnType(data_type="basic", data_type_name="long"),
        property_type="system",
        annotation="charge amount",
    )
    candidate = NamingSqlCandidate(
        candidate_id="candidate.bound",
        bo_name=bo.bo_name,
        naming_sql_id="E_QUERY_CHARGE",
        naming_sql_name="E_QUERY_CHARGE",
        param_list=[{"param_name": "CHARGE_AMT", "data_type_name": "long"}],
        return_type={"data_type": "bo", "data_type_name": bo.bo_name, "is_list": False},
        source="resource_registry",
        rank=0,
    )
    selection = NamingSqlSelectResponse(success=True, selection_mode=SelectionMode.DETERMINISTIC_FALLBACK,
                                        candidates=[candidate])

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(
                selected_global_contexts=[context_value],
                selected_bos=[bo],
                naming_sql_selection=selection,
            ),
            loaded=loaded_resource(contexts=[context_value], bos=[bo]),
        )
    )

    assert result.var_templates[0].definition_expr == (
        "fetch_one(E_QUERY_CHARGE, pair(it.CHARGE_AMT, $ctx$.chargeAmt))"
    )


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


def test_builder_expands_list_methods_and_first_object_fields():
    bo = charge_bo()
    charges = ContextRegistry(
        resource_id="ctx.charges",
        context_name="$ctx$.charges",
        return_type=ReturnType(data_type="bo", data_type_name=bo.bo_name, is_list=True),
        property_type="system",
        annotation="charges",
    )
    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(
                selected_global_contexts=[charges],
                selected_bos=[bo],
            ),
            loaded=loaded_resource(contexts=[charges], bos=[bo]),
        )
    )

    root = result.root_values[0]
    assert [method.split("(", 1)[0] for method in next(item.methods for item in result.method_catalog if item.owner_type == root.return_type)] == [
        "first",
        "size",
        "find{expr}",
        "findAll{expr}",
    ]
    assert any(
        field.access == "$ctx$.charges.first().CHARGE_AMT"
        and field.return_type == "basic.long"
        for field in root.fields
    )


def test_builder_expands_beyond_four_object_layers_until_basic():
    registry = TypeRegistry()
    for index in range(1, 6):
        registry.register_type(
            TypeDef(
                owner_type=TypeRef(kind="logic", name=f"Level{index}"),
                fields={
                    f"level{index + 1}": TypeRef(kind="logic", name=f"Level{index + 1}")
                },
            )
        )
    registry.register_type(
        TypeDef(
            owner_type=TypeRef(kind="logic", name="Level6"),
            fields={"value": TypeRef(kind="basic", name="String")},
        )
    )
    root_context = ContextRegistry(
        resource_id="ctx.deep",
        context_name="$ctx$.deep",
        return_type=ReturnType(data_type="logic", data_type_name="Level1"),
        property_type="system",
        annotation="deep",
    )

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[root_context]),
            loaded=loaded_resource(contexts=[root_context]),
            type_registry=registry,
        )
    )

    assert result.root_values[0].fields[-1].access.endswith(
        ".level2.level3.level4.level5.level6.value"
    )
    assert result.root_values[0].fields[-1].return_type == "basic.String"


def test_builder_cuts_recursive_type_cycle_with_warning():
    registry = TypeRegistry()
    registry.register_type(
        TypeDef(
            owner_type=TypeRef(kind="logic", name="Node"),
            fields={"child": TypeRef(kind="logic", name="Node")},
        )
    )
    root_context = ContextRegistry(
        resource_id="ctx.node",
        context_name="$ctx$.node",
        return_type=ReturnType(data_type="logic", data_type_name="Node"),
        property_type="system",
        annotation="node",
    )

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[root_context]),
            loaded=loaded_resource(contexts=[root_context]),
            type_registry=registry,
        )
    )

    assert [field.access for field in result.root_values[0].fields] == ["$ctx$.node.child"]
    assert result.warnings == ["recursive type cycle at $ctx$.node.child: logic.Node"]


def test_builder_applies_global_item_budget_and_prioritizes_query_field():
    registry = TypeRegistry()
    registry.register_type(
        TypeDef(
            owner_type=TypeRef(kind="logic", name="ChargeView"),
            fields={
                "OTHER": TypeRef(kind="basic", name="String"),
                "CHARGE_AMT": TypeRef(kind="basic", name="long"),
            },
        )
    )
    root_context = ContextRegistry(
        resource_id="ctx.charge",
        context_name="$ctx$.charge",
        return_type=ReturnType(data_type="logic", data_type_name="ChargeView"),
        property_type="system",
        annotation="charge",
    )
    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[root_context]),
            loaded=loaded_resource(contexts=[root_context]),
            type_registry=registry,
            max_items=2,
        )
    )

    item_count = (
        len(result.root_values)
        + sum(len(root.fields) for root in result.root_values)
        + len(result.var_templates)
        + sum(len(template.available_fields) for template in result.var_templates)
        + len(result.method_catalog)
        + len(result.expression_patterns)
    )
    assert item_count <= 2
    assert [field.access for field in result.root_values[0].fields] == [
        "$ctx$.charge.CHARGE_AMT"
    ]


def test_builder_expands_map_get_value_fields():
    bo = charge_bo()
    map_type = TypeRef(
        kind="map",
        key_type=TypeRef(kind="basic", name="String"),
        value_type=TypeRef(kind="bo", name=bo.bo_name),
    )
    charge_map = ContextRegistry.model_construct(
        resource_id="ctx.charge_map",
        context_name="$ctx$.chargeMap",
        return_type=map_type,
        property_type="system",
        annotation="charge map",
        tag=[],
    )
    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(
                selected_global_contexts=[charge_map],
                selected_bos=[bo],
            ),
            loaded=loaded_resource(contexts=[charge_map], bos=[bo]),
        )
    )

    root = result.root_values[0]
    assert next(item.methods for item in result.method_catalog if item.owner_type == root.return_type) == ["get(basic.String k): bo.BB_BILL_CHARGE"]
    assert any(
        field.access == "$ctx$.chargeMap.get(...).CHARGE_AMT"
        for field in root.fields
    )


def test_builder_prioritizes_bo_field_annotation_match_under_budget():
    bo = BoRegistry(
        resource_id="bo.annotation",
        bo_name="ANNOTATED_BO",
        bo_desc="annotated",
        property_list=[
            PropertyTerm(
                field_name="A_FIELD",
                description="unrelated",
                data_type=DataTypeEnum.basic,
                data_type_name="String",
            ),
            PropertyTerm(
                field_name="Z_FIELD",
                description="preferred semantic amount",
                data_type=DataTypeEnum.basic,
                data_type_name="long",
            ),
        ],
    )
    rows = ContextRegistry(
        resource_id="ctx.annotated",
        context_name="$ctx$.annotated",
        return_type=ReturnType(data_type="bo", data_type_name=bo.bo_name, is_list=True),
        property_type="system",
        annotation="rows",
    )
    request = build_input(
        filtered_env=FilteredEnvironment(
            selected_global_contexts=[rows],
            selected_bos=[bo],
        ),
        loaded=loaded_resource(contexts=[rows], bos=[bo]),
        max_items=2,
    ).model_copy(update={"query": "preferred semantic amount", "node": NodeDef(node_id="n", node_path="$.n", node_name="NONE")})

    result = TypedExpressionContextBuilder().build(request)

    assert [field.access for field in result.root_values[0].fields] == [
        "$ctx$.annotated.first().Z_FIELD"
    ]


def _basic_context(name: str, *, local: bool = False, property_type: str = "system"):
    cls = LocalContextRegistry if local else ContextRegistry
    return cls(
        resource_id=f"context.{name}",
        context_name=name,
        return_type=ReturnType(data_type="basic", data_type_name="String"),
        property_type=property_type,
        annotation=name,
        **({"source_path": "$.n"} if local else {}),
    )


def test_builder_promotes_explicit_global_path_over_nearer_scopes():
    unrelated_global = _basic_context("$ctx$.unrelated")
    global_context = _basic_context("$ctx$.required")
    local_context = _basic_context("$local$.near", local=True, property_type="local")
    request = build_input(
        filtered_env=FilteredEnvironment(
            selected_global_contexts=[unrelated_global, global_context],
            visible_local_context=[local_context],
        ),
        loaded=loaded_resource(contexts=[unrelated_global, global_context]),
        max_items=1,
    ).model_copy(update={"query": "use $ctx$.required"})

    result = TypedExpressionContextBuilder().build(request)

    assert [root.expr for root in result.root_values] == ["$ctx$.required"]


def test_builder_admits_near_scope_roots_before_field_details():
    bo = BoRegistry(
        resource_id="bo.large",
        bo_name="LARGE_BO",
        bo_desc="large",
        property_list=[
            PropertyTerm(field_name=name, data_type=DataTypeEnum.basic, data_type_name="String")
            for name in ("A", "B", "C")
        ],
    )
    iterator = LocalContextRegistry(
        resource_id="context.iter",
        context_name="$iter$",
        return_type=ReturnType(data_type="bo", data_type_name=bo.bo_name),
        property_type="iter",
        annotation="iterator",
        source_path="$.n",
    )
    local_context = _basic_context("$local$.near", local=True, property_type="local")
    global_context = _basic_context("$ctx$.far")

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(
                selected_global_contexts=[global_context],
                visible_local_context=[local_context, iterator],
                selected_bos=[bo],
            ),
            loaded=loaded_resource(contexts=[global_context], bos=[bo]),
            max_items=3,
        )
    )

    assert [root.expr for root in result.root_values] == [
        "$iter$",
        "$local$.near",
        "$ctx$.far",
    ]
    assert result.root_values[0].fields == []


def test_builder_serializes_methods_once_per_referenced_type():
    first = _basic_context("$ctx$.first")
    second = _basic_context("$ctx$.second")

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[first, second]),
            loaded=loaded_resource(contexts=[first, second]),
        )
    )
    serialized = result.model_dump()

    assert all("methods" not in root for root in serialized["root_values"])
    assert [item.owner_type for item in result.method_catalog].count("basic.String") == 1


def test_builder_reports_budget_truncation_once():
    first = _basic_context("$ctx$.first")
    second = _basic_context("$ctx$.second")

    result = TypedExpressionContextBuilder().build(
        build_input(
            filtered_env=FilteredEnvironment(selected_global_contexts=[first, second]),
            loaded=loaded_resource(contexts=[first, second]),
            max_items=1,
        )
    )

    assert result.warnings.count("typed context truncated by max_items budget") == 1
