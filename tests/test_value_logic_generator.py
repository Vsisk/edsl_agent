import pytest

from agent.context_manager.models import NamingSqlCandidate
from agent.context_manager.errors import NO_NAMING_SQL_CANDIDATES
from agent.context_pack.models import ContextPack
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.models import ValueLogicRequest
from agent.naming_sql_selector import NamingSqlSelectResponse, SelectionMode
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.value_logic_generator import ExpressionSpec, ValueLogicGenerator, requires_naming_sql
from tests.test_environment import FakeResourceFilter, sample_edsl_tree_payload


class Targets:
    def generate(self, **kwargs): return []


class Specs:
    def __init__(self, events=None): self.events = events
    def generate(self, *, request, node_info, context_pack=None):
        if self.events is not None: self.events.append(("spec", context_pack))
        return ExpressionSpec(nl=request.query)


class Planner:
    def __init__(self, fetch=True): self.calls, self.fetch = [], fetch
    def plan(self, **kwargs):
        self.calls.append(kwargs)
        if self.fetch:
            return Plan.model_validate({"nodes": [{"type": "return", "value": {"type": "fetch_one",
                "name": "FindCustomerRecent", "params": [{"name": "id", "value": {"type": "literal", "value": "x"}}]}}]})
        return Plan.model_validate({"nodes": [{"type": "return", "value": {"type": "literal", "value": "ok"}}]})


class Selector:
    def __init__(self, result): self.result, self.calls = result, []
    def select(self, request): self.calls.append(request); return self.result


class Route:
    def __init__(self, use_bo, use_function, resource_count_hint=5):
        self.use_bo, self.use_function = use_bo, use_function
        self.resource_count_hint = resource_count_hint


class Router:
    def __init__(self, route): self.route, self.calls = route, []
    def route_resources(self, **kwargs): self.calls.append(kwargs); return self.route


class SelectPlanner(Planner):
    def __init__(self): super().__init__(fetch=False)
    def plan(self, **kwargs):
        self.calls.append(kwargs)
        return Plan.model_validate({"nodes": [{"type": "return", "value": {"type": "select_one",
            "bo": "BB_PREP_SUB", "filter": {"type": "compare", "op": "==",
                "left": {"type": "context_path", "path": "it.ID"},
                "right": {"type": "context_path", "path": "$ctx$.id"}}}}]})


def candidate(cid, name, rank):
    return NamingSqlCandidate(candidate_id=f"internal:{cid}", bo_name="BB_BAK_TRANS", naming_sql_id=cid,
        naming_sql_name=name, param_list=[{"param_name": "id", "data_type_name": "String"}],
        source="resource_registry", rank=rank)


def success():
    return NamingSqlSelectResponse(success=True, selection_mode=SelectionMode.DETERMINISTIC_FALLBACK,
        candidates=[candidate("a", "FindCustomer", 1),
        candidate("b", "FindCustomerRecent", 2)])


def request(route=True):
    return ValueLogicRequest(site_id="site1", project_id="project1", node_path="$.x",
        node={"node_id": "x", "name": "x", "reference_logic_area_id_list": ["area.1"]},
        parent_node={"data_source_type": "sql", "bo_name": "ParentBO"}, query="use naming sql" if route else "ordinary",
        structured_spec={"requires_naming_sql": route, "bo_name": "BB_BAK_TRANS"}, edsl_tree=sample_edsl_tree_payload())


def generator(factory, planner, context_pack_manager=None, context_resource_router=None, specs=None):
    return ValueLogicGenerator(resource_loader=ResourceLoader(), llm_planner=planner,
        naming_sql_selector_factory=factory, expression_spec_generator=specs or Specs(),
        resource_filter_target_generator=Targets(), context_pack_manager=context_pack_manager,
        context_resource_router=context_resource_router)


class ContextRoute:
    def __init__(self, use_current_tree, fallback=False):
        self.use_current_tree, self.fallback, self.calls = use_current_tree, fallback, []
    def route(self, **kwargs): self.calls.append(kwargs); return self


class CapturingPacks:
    def __init__(self): self.calls, self.pack = [], None
    def build(self, pack_request, project_context):
        self.calls.append((pack_request, project_context))
        self.pack = ContextPack(status="complete", request_summary={"query": pack_request.query},
                                current_node=pack_request.node)
        return self.pack


def test_context_pack_is_built_once_before_spec_and_fixed_resources_are_always_used():
    events, packs = [], CapturingPacks()
    route = ContextRoute(False)
    planner = Planner(fetch=False)
    generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner,
              packs, route, Specs(events)).generate(request(False))
    assert len(packs.calls) == 1
    assert packs.calls[0][0].resource_names == ["dev_skill", "ootb_edsl"]
    assert events == [("spec", packs.pack)]
    assert packs.pack is not None
    assert planner.calls[0]["context_pack"] is packs.pack


def test_context_route_fallback_builds_all_resources():
    packs = CapturingPacks()
    selector = Selector(success())
    generator(lambda loaded: selector, Planner(), packs,
              ContextRoute(True, fallback=True)).generate(request())
    assert [item.value for item in packs.calls[0][0].resource_names] == [
        "dev_skill", "ootb_edsl", "current_tree"
    ]
    assert selector.calls[0].context_pack.warnings[0].code == "CONTEXT_RESOURCE_ROUTE_FALLBACK"


def test_non_naming_sql_route_does_not_construct_factory_and_regresses_ordinary_path():
    planner = Planner(fetch=False)
    def fail(_): raise AssertionError("factory must not be called")
    result = generator(fail, planner).generate(request(False))
    assert result.expression == '"ok"' and planner.calls[0]["filtered_env"].naming_sql_selection is None


def test_route_factory_receives_current_loaded_resource_and_request_fields():
    planner, seen, events = Planner(), [], []
    selector = Selector(success())
    class Packs:
        def __init__(self): self.pack = None
        def build(self, pack_request, project_context):
            events.append(("pack", pack_request, project_context))
            self.pack = ContextPack(status="complete", request_summary={"query": pack_request.query},
                                    current_node=pack_request.node)
            return self.pack
    def factory(loaded): events.append(("selector",)); seen.append(loaded); return selector
    packs = Packs()
    generator(factory, planner, packs, ContextRoute(False)).generate(request())
    call = selector.calls[0]
    assert [event[0] for event in events] == ["pack", "selector"]
    assert call.context_pack is packs.pack
    assert events[0][2].loaded_resource is seen[0]
    assert seen and call.site_id == "site1" and call.project_id == "project1" and call.json_path == "$.x"
    assert call.target_bo_name == "BB_BAK_TRANS" and call.parent_bo_hint == "ParentBO"
    assert call.target_logic_area_id_list == ["area.1"] and call.top_k == 5


def test_known_selector_failure_raises_exact_documented_code_and_stops_planner():
    planner = Planner()
    selector = Selector(NamingSqlSelectResponse(success=False, failure_reason=NO_NAMING_SQL_CANDIDATES))
    with pytest.raises(ValueError) as raised:
        generator(lambda loaded: selector, planner).generate(request())
    assert str(raised.value) == NO_NAMING_SQL_CANDIDATES
    assert not planner.calls


def test_unknown_selector_failure_is_generic_and_does_not_leak_private_detail():
    planner = Planner()
    selector = Selector(NamingSqlSelectResponse(success=False, failure_reason="PRIVATE backend detail\nsecret"))
    with pytest.raises(ValueError) as raised:
        generator(lambda loaded: selector, planner).generate(request())
    assert str(raised.value) == "NAMING_SQL_SELECTION_FAILED"
    assert "PRIVATE" not in str(raised.value) and "secret" not in str(raised.value)
    assert not planner.calls


def test_success_reaches_planner_with_all_top_k_and_without_narrowing_loaded_resource():
    planner, loaded_seen = Planner(), []
    selector = Selector(success())
    def factory(loaded): loaded_seen.append(loaded); return selector
    generator(factory, planner).generate(request())
    env = planner.calls[0]["filtered_env"]
    assert [item.naming_sql_name for item in env.naming_sql_selection.candidates] == ["FindCustomer", "FindCustomerRecent"]
    assert len(loaded_seen[0].bo_registry["BB_BAK_TRANS"].naming_sql_list) == 1


def test_generator_builds_typed_context_after_filtering_and_passes_it_to_planner():
    planner = Planner(fetch=False)
    typed_context = TypedExpressionContext(warnings=["captured"])

    class CapturingBuilder:
        def __init__(self): self.inputs = []
        def build(self, build_input):
            self.inputs.append(build_input)
            return typed_context

    builder = CapturingBuilder()
    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        expression_spec_generator=Specs(),
        resource_filter_target_generator=Targets(),
        typed_expression_context_builder=builder,
    )

    gen.generate(request(False))

    assert len(builder.inputs) == 1
    assert builder.inputs[0].filtered_env is planner.calls[0]["filtered_env"]
    assert builder.inputs[0].loaded_resource.bo_registry is not None
    assert builder.inputs[0].context_pack is not None
    assert planner.calls[0]["typed_context"] is typed_context


@pytest.mark.parametrize("signal", [
    "查表", "查询表", "data source", "data_source", "data-source",
    "naming sql", "naming_sql", "naming-sql",
])
def test_prior_naming_sql_route_signal_variants_are_preserved(signal):
    assert requires_naming_sql({}, signal)


def test_explicit_route_boolean_has_precedence_over_inferred_signals():
    assert requires_naming_sql({"requires_naming_sql": True}, "ordinary")
    assert not requires_naming_sql({"requires_naming_sql": False}, "use naming sql")


def test_each_route_input_gets_a_fair_share_of_the_combined_bound():
    long_query = "x" * 4000
    assert requires_naming_sql({}, long_query, "use naming sql", {}, None)
    assert requires_naming_sql({}, long_query, "ordinary", {"annotation": "data source"}, None)
    assert requires_naming_sql({}, long_query, "ordinary", {}, {"annotation": "查询表"})


@pytest.mark.parametrize("value", ["renamingsqltable", "mydatasourcevalue"])
def test_route_terms_do_not_match_inside_larger_ascii_identifiers(value):
    assert not requires_naming_sql({}, value)


def test_summary_field_bypasses_factory_and_planner():
    planner = Planner(fetch=False)
    def fail(_): raise AssertionError("factory must not be called")
    summary_request = request(False).model_copy(update={"is_ab": True, "node": {
        "node_id": "sum", "name": "total", "field_type": "summary",
        "summary_type": "sum", "detail_field": "AMOUNT",
    }})
    result = generator(fail, planner).generate(summary_request)
    assert result.logic_type == "summary" and result.source.summary_type == "sum"
    assert result.source.detail_field == "AMOUNT" and not planner.calls


def test_default_filter_path_uses_expression_spec_text():
    class CapturingTargets:
        def __init__(self): self.calls = []
        def generate(self, **kwargs): self.calls.append(kwargs); return []
    targets, planner = CapturingTargets(), Planner(fetch=False)
    gen = ValueLogicGenerator(resource_loader=ResourceLoader(), llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        expression_spec_generator=Specs(), resource_filter_target_generator=targets)
    gen.generate(request(False))
    assert targets.calls[0]["query"] == "ordinary"


def test_parent_sql_direct_field_mapping_still_bypasses_planner():
    planner = Planner(fetch=False)
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "log", "name": "LOG_ID", "is_ab": True},
        "parent_node": {"data_source_type": "sql", "bo_name": "BB_BAK_TRANS"},
        "query": "direct BO field mapping",
    })
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(req)
    assert result.logic_type == "bo_field_mapping" and result.expression == "LOG_ID"
    assert not planner.calls


def test_empty_targets_keep_empty_environment_and_trace():
    planner = Planner(fetch=False)
    generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(request(False))
    env = planner.calls[0]["filtered_env"]
    assert env.selected_global_context_ids == []
    assert env.selection_trace[-1]["reason"] == "FILTER_TARGET_EMPTY"


def test_simple_leaf_renders_existing_select_plan():
    planner = SelectPlanner()
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(request(False))
    assert result.expression == "select_one(BB_PREP_SUB, it.ID == $ctx$.id)"
    assert result.source.source_type == "plan"


def _legacy_generator(route, result, planner=None):
    resource_filter = FakeResourceFilter(result)
    planner = planner or Planner(fetch=False)
    gen = ValueLogicGenerator(resource_loader=ResourceLoader(), llm_resource_filter=resource_filter,
        llm_difficulty_router=Router(route), llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        expression_spec_generator=Specs(), resource_filter_target_generator=Targets(),
        enable_legacy_filter_fallback=True)
    return gen, resource_filter, planner


@pytest.mark.parametrize(("route", "expected_bo", "expected_function"), [
    (Route(False, False), [], []),
    (Route(True, False), ["bo.0000"], []),
    (Route(False, True), [], ["func.0001"]),
])
def test_legacy_fallback_gates_context_bo_and_function_groups(route, expected_bo, expected_function):
    result = {"bo": [{"resource_id": "bo.0000"}], "function": [{"resource_id": "func.0001"}],
        "local_context": [{"resource_id": "local.0001"}], "global_context": [{"resource_id": "ctx.0001"}]}
    gen, resource_filter, planner = _legacy_generator(route, result)
    query = (
        "lookup BO by CUST_ID with local_2 context"
        if route.use_bo
        else "mask CUST_ID with function and local_2 context"
        if route.use_function
        else "assign CUST_ID from local_2 context directly"
    )
    gen.generate(request(False).model_copy(update={"node_path": "$.mapping_content.children[1]", "query": query}))
    env, call = planner.calls[0]["filtered_env"], resource_filter.calls[0]
    assert env.selected_bo_ids == expected_bo
    assert env.selected_function_ids[:len(expected_function)] == expected_function
    if not route.use_function:
        assert env.selected_function_ids == []
    assert env.selected_local_context_ids[0] == "local.0001" and env.selected_global_context_ids[0] == "ctx.0001"
    assert call["limits"]["bo"] == (5 if route.use_bo else 0)
    assert call["limits"]["function"] == (5 if route.use_function else 0)


@pytest.mark.parametrize(("route", "expected"), [
    (Route(True, True, 9), {"global_context": 9, "local_context": 9, "bo": 9, "function": 9}),
    (Route(False, False, 12), {"global_context": 12, "local_context": 12, "bo": 0, "function": 0}),
])
def test_legacy_fallback_dynamic_limits_and_disabled_groups(route, expected):
    gen, resource_filter, _ = _legacy_generator(route, {})
    gen.generate(request(False).model_copy(update={"query": "use CUST_ID LOG_ID and mask resources"}))
    assert resource_filter.calls[0]["limits"] == expected


def _ab_request(*, source_type="sql", field="LOG_ID", query="directly map LOG_ID from table field"):
    return request(False).model_copy(update={"is_ab": True, "node": {
        "node_id": "normal-field", "tree_node_type": "field", "xml_name_property": {"xml_name": field}},
        "parent_node": {"node_id": "ab-parent", "is_ab": True, "ab_content": {"data_source": {
            "data_source_type": source_type, "sql_query": {"bo_name": "BB_BAK_TRANS"}}}}, "query": query})


def test_complex_ab_sql_parent_path_maps_loaded_bo_field():
    planner = SelectPlanner()
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(_ab_request())
    assert result.logic_type == "bo_field_mapping" and result.expression == "LOG_ID"
    assert result.source.bo_name == "BB_BAK_TRANS" and not planner.calls


def test_ab_sql_missing_bo_field_falls_back_to_plan():
    planner = SelectPlanner()
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(
        _ab_request(field="MISSING_FIELD", query="map or derive missing field"))
    assert result.logic_type == "expression" and len(planner.calls) == 1


def test_ab_sql_existing_field_uses_plan_for_complex_expression_intent():
    planner = SelectPlanner()
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(
        _ab_request(query="derive a formatted LOG_ID with fallback when missing"))
    assert result.logic_type == "expression" and result.source.source_type == "plan"
    assert len(planner.calls) == 1


def test_ab_non_sql_parent_does_not_use_nested_bo_name():
    planner = SelectPlanner()
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(
        _ab_request(source_type="expression", query="derive log id"))
    assert result.logic_type == "expression" and len(planner.calls) == 1
