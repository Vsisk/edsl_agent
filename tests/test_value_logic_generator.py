import inspect

import pytest

from agent.context_manager.errors import NO_NAMING_SQL_CANDIDATES
from agent.context_pack.models import ContextPack
from agent.expression_generation.typed_context import TypedExpressionContext
from agent.models import ValueLogicRequest, ValueLogicResult, ValueLogicSource
from agent.resource_manager.loader.namingsql_profile_loader import NamingSqlProfile
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.resource_manager.loader.registry_models import ReturnType
from agent.spec_orchestration.models import (
    GoalRole,
    SpecOrchestrationResult,
    ValueGoal,
)
from agent.value_logic_generator import ValueLogicGenerator, requires_naming_sql
from tests.test_environment import FakeResourceFilter, StaticResourceLoader, sample_edsl_tree_payload
from tests.test_resource_loader import sample_bo_payload


class Targets:
    def generate(self, **kwargs): return []


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
    def select(self, **request): self.calls.append(request); return self.result


class FirstProfileSelector:
    def __init__(self): self.calls = []
    def select(self, **request):
        self.calls.append(request)
        return request["profiles"][:1]


class SqlResourceLoader(StaticResourceLoader):
    def __init__(self):
        super().__init__({"bo": sample_bo_payload()})


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
    return NamingSqlProfile(bo_name="BB_BAK_TRANS", namingsql_name=name,
        where_conditions=[], return_fields=[], performance_optimized=False)


def success():
    return [candidate("a", "FindCustomer", 1), candidate("b", "FindCustomerRecent", 2)]


def request(route=True):
    return ValueLogicRequest(site_id="site1", project_id="project1", node_path="$.x",
        node={"node_id": "x", "name": "x", "reference_logic_area_id_list": ["area.1"]},
        parent_node={"data_source_type": "sql", "bo_name": "ParentBO"}, query="use naming sql" if route else "ordinary",
        structured_spec={"requires_naming_sql": route, "bo_name": "BB_BAK_TRANS"}, edsl_tree=sample_edsl_tree_payload())


def generator(factory, planner, context_pack_manager=None, context_resource_router=None):
    return ValueLogicGenerator(resource_loader=ResourceLoader(), llm_planner=planner,
        naming_sql_selector_factory=factory,
        resource_filter_target_generator=Targets(), context_pack_manager=context_pack_manager,
        context_resource_router=context_resource_router)


class BranchSpyGenerator(ValueLogicGenerator):
    def __init__(self):
        super().__init__(
            resource_loader=ResourceLoader(),
            llm_planner=Planner(fetch=False),
            naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
            resource_filter_target_generator=Targets(),
        )
        self.branch_calls = []

    def _branch_result(self, branch):
        self.branch_calls.append(branch)
        return ValueLogicResult(
            node_id=branch,
            logic_type="expression",
            expression=branch,
            source=ValueLogicSource(source_type="plan"),
        )

    def _generate_sql_branch(self, request, ctx):
        return self._branch_result("sql")

    def _generate_expression_branch(self, request, ctx):
        return self._branch_result("expression")

    def _generate_table_field_branch(self, request, ctx):
        return self._branch_result("table_field")

    def _generate_summary_branch(self, request, ctx):
        return self._branch_result("summary")


@pytest.mark.parametrize(
    ("node", "is_ab", "expected_branch"),
    [
        ({"node_id": "leaf", "tree_node_type": "simple_leaf"}, False, "expression"),
        ({"node_id": "ab", "tree_node_type": "ab_pivot_table"}, True, "sql"),
        ({"field_id": "field", "tree_node_type": "ab_pivot_table"}, True, "table_field"),
        (
            {"field_id": "sum", "tree_node_type": "ab_pivot_table", "field_type": "summary"},
            True,
            "summary",
        ),
    ],
)
def test_value_logic_target_dispatches_to_branch(node, is_ab, expected_branch):
    gen = BranchSpyGenerator()
    req = request(False).model_copy(update={"node": node, "is_ab": is_ab})

    result = gen.generate(req)

    assert result.expression == expected_branch
    assert gen.branch_calls == [expected_branch]


def test_sql_branch_selects_bo_then_namingsql_and_returns_sql_result():
    planner = Planner(fetch=False)
    selector = FirstProfileSelector()
    bo_calls = []
    param_calls = []

    def choose_bo(**kwargs):
        bo_calls.append(kwargs)
        return "BB_BAK_TRANS"

    def bind_params(**kwargs):
        param_calls.append(kwargs)
        return [
            {
                "param_name": "END_DATE",
                "param_value": "2026-08-04",
            }
        ]

    gen = ValueLogicGenerator(
        resource_loader=SqlResourceLoader(),
        llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: selector,
        resource_filter_target_generator=Targets(),
        sql_bo_selector=choose_bo,
        sql_param_binder=bind_params,
        sql_table_query_counter=lambda **kwargs: 1,
    )
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "ab", "tree_node_type": "parent_list", "name": "transactions"},
        "query": "query transaction list by end date",
    })

    result = gen.generate(req)

    assert result.logic_type == "sql"
    assert result.expression == "BB_BAK_TRANS_queryDataLoadData"
    assert result.source.source_type == "sql"
    assert result.source.bo_name == "BB_BAK_TRANS"
    assert result.source.sql_name == "BB_BAK_TRANS_queryDataLoadData"
    assert result.source.sql_params == [
        {"param_name": "END_DATE", "param_value": "2026-08-04"},
    ]
    assert result.return_type.is_list is True
    assert result.return_type.data_type_name == "BB_BAK_TRANS"
    assert not planner.calls
    assert bo_calls and "BB_BAK_TRANS" in bo_calls[0]["bo_candidates_json"]
    assert [profile.bo_name for profile in selector.calls[0]["profiles"]] == ["BB_BAK_TRANS"]
    assert param_calls and "END_DATE" in param_calls[0]["params_json"]


def test_sql_branch_falls_back_to_expression_when_bo_is_not_selected():
    planner = Planner(fetch=False)

    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        resource_filter_target_generator=Targets(),
        sql_bo_selector=lambda **kwargs: None,
    )
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "ab", "tree_node_type": "parent_list", "name": "transactions"},
        "query": "query transaction list",
    })

    result = gen.generate(req)

    assert result.logic_type == "expression"
    assert planner.calls


def test_sql_branch_skips_sql_selection_when_query_needs_multiple_table_queries():
    planner = Planner(fetch=False)

    def fail_bo(**kwargs):
        raise AssertionError("BO selection must not run")

    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        resource_filter_target_generator=Targets(),
        sql_bo_selector=fail_bo,
        sql_table_query_counter=lambda **kwargs: 2,
    )
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "ab", "tree_node_type": "parent_list", "name": "transactions"},
        "query": "query transactions then query customer details",
    })

    result = gen.generate(req)

    assert result.logic_type == "expression"
    assert planner.calls


def test_sql_branch_uses_empty_string_defaults_when_param_binding_is_incomplete():
    planner = Planner(fetch=False)
    selector = FirstProfileSelector()

    gen = ValueLogicGenerator(
        resource_loader=SqlResourceLoader(),
        llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: selector,
        resource_filter_target_generator=Targets(),
        sql_bo_selector=lambda **kwargs: "BB_BAK_TRANS",
        sql_param_binder=lambda **kwargs: [],
        sql_table_query_counter=lambda **kwargs: 1,
    )
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "ab", "tree_node_type": "parent_list", "name": "transactions"},
        "query": "query transaction list",
    })

    result = gen.generate(req)

    assert result.logic_type == "sql"
    assert result.source.sql_params == [
        {"param_name": "END_DATE", "param_value": ""},
    ]
    assert not planner.calls


@pytest.mark.parametrize("failing_stage", ["resource_filter", "planner"])
def test_expression_pipeline_retries_transient_stage_errors(monkeypatch, failing_stage):
    calls = {"resource_filter": 0, "planner": 0}
    feedback_seen = {"resource_filter": [], "planner": []}

    class FlakyTargets(Targets):
        def generate(self, **kwargs):
            calls["resource_filter"] += 1
            feedback_seen["resource_filter"].append(kwargs.pop("retry_feedback", None))
            if failing_stage == "resource_filter" and calls["resource_filter"] == 1:
                raise RuntimeError("transient filter error")
            return super().generate(**kwargs)

    class FlakyPlanner(Planner):
        def plan(self, **kwargs):
            calls["planner"] += 1
            feedback_seen["planner"].append(kwargs.pop("retry_feedback", None))
            if failing_stage == "planner" and calls["planner"] == 1:
                raise RuntimeError("transient planner error")
            return super().plan(**kwargs)

    planner = FlakyPlanner(fetch=False)
    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        resource_filter_target_generator=FlakyTargets(),
    )

    result = gen.generate(request(False))

    assert result.expression == '"ok"'
    assert calls[failing_stage] == 2
    assert feedback_seen[failing_stage][1]["stage"] == failing_stage
    assert feedback_seen[failing_stage][1]["error_type"] == "RuntimeError"
    expected_message = {
        "resource_filter": "transient filter error",
        "planner": "transient planner error",
    }[failing_stage]
    assert expected_message in feedback_seen[failing_stage][1]["message"]


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


def test_context_pack_is_built_once_and_fixed_resources_are_always_used():
    packs = CapturingPacks()
    route = ContextRoute(False)
    planner = Planner(fetch=False)
    generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner,
              packs, route).generate(request(False))
    assert len(packs.calls) == 1
    assert packs.calls[0][0].resource_names == ["dev_skill", "ootb_edsl"]
    assert packs.pack is not None
    assert planner.calls[0]["context_pack"] is packs.pack


@pytest.mark.skip(reason="obsolete ContextPack selector request contract removed")
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
    assert result.expression == '"ok"' and planner.calls[0]["filtered_env"].naming_sql_selection == []


def test_default_resource_pipeline_can_be_replaced_by_spec_orchestrator():
    events = []

    class Orchestrator:
        def resolve(self, **kwargs):
            events.append(("orchestrator", kwargs["query"]))
            assert "base_spec" not in kwargs
            assert kwargs["request"].query == "ordinary"
            assert kwargs["context_pack"] is not None
            goal = ValueGoal(
                goal_id="root",
                semantic_name="ordinary",
                role=GoalRole.FINAL_OUTPUT,
                expected_type=ReturnType(
                    data_type="basic", data_type_name="string", is_list=False
                ),
            )
            return SpecOrchestrationResult(
                query=kwargs["query"],
                root_goal=goal,
                failed_goal_ids=["root"],
            )

    planner = Planner(fetch=False)
    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        query_spec_clarity_analyzer=type(
            "Analyzer",
            (),
            {"is_explicit_spec": lambda self, **_: False},
        )(),
        spec_orchestrator_factory=lambda loaded: Orchestrator(),
    )

    result = gen.generate(request(False))

    assert result.expression == '"ok"'
    assert events == [("orchestrator", "ordinary")]
    assert planner.calls[0]["expression_spec"].nl == "ordinary"


def test_explicit_query_spec_bypasses_spec_generation_and_filters_resources_directly():
    events = []

    class Analyzer:
        def is_explicit_spec(self, **kwargs):
            events.append(("clarity", kwargs["query"]))
            return True

    class CapturingTargets(Targets):
        def generate(self, **kwargs):
            events.append(("filter", kwargs["query"]))
            return []

    class FlakyPlanner(Planner):
        def plan(self, **kwargs):
            if not self.calls:
                self.calls.append(kwargs)
                raise RuntimeError("retry planner")
            return super().plan(**kwargs)

    planner = FlakyPlanner(fetch=False)
    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=planner,
        query_spec_clarity_analyzer=Analyzer(),
        resource_filter_target_generator=CapturingTargets(),
        spec_orchestrator_factory=lambda _: (_ for _ in ()).throw(
            AssertionError("explicit spec must bypass spec generation")
        ),
    )

    result = gen.generate(request(False))

    assert result.expression == '"ok"'
    assert [event for event in events if event[0] == "clarity"] == [
        ("clarity", "ordinary")
    ]
    assert [event[0] for event in events].count("filter") == 2


def test_unclear_query_spec_runs_existing_spec_generation_path():
    events = []

    class Analyzer:
        def is_explicit_spec(self, **kwargs):
            events.append(("clarity", kwargs["query"]))
            return False

    class Orchestrator:
        def resolve(self, **kwargs):
            events.append(("orchestrator", kwargs["query"]))
            goal = ValueGoal(
                goal_id="root",
                semantic_name=kwargs["query"],
                role=GoalRole.FINAL_OUTPUT,
                expected_type=kwargs["expected_type"],
            )
            return SpecOrchestrationResult(
                query=kwargs["query"],
                root_goal=goal,
                failed_goal_ids=["root"],
            )

    class FailTargets(Targets):
        def generate(self, **kwargs):
            raise AssertionError("unclear query must not bypass spec generation")

    gen = ValueLogicGenerator(
        resource_loader=ResourceLoader(),
        llm_planner=Planner(fetch=False),
        query_spec_clarity_analyzer=Analyzer(),
        resource_filter_target_generator=FailTargets(),
        spec_orchestrator_factory=lambda _: Orchestrator(),
    )

    result = gen.generate(request(False))

    assert result.expression == '"ok"'
    assert events == [("clarity", "ordinary"), ("orchestrator", "ordinary")]


def test_value_logic_generator_no_longer_exposes_expression_spec_generator():
    assert (
        "expression_spec_generator"
        not in inspect.signature(ValueLogicGenerator.__init__).parameters
    )


@pytest.mark.skip(reason="selector now receives query and profiles inside filter env")
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


def test_success_reaches_planner_with_all_top_k_and_without_narrowing_loaded_resource():
    planner, loaded_seen = Planner(), []
    selector = Selector(success())
    def factory(loaded): loaded_seen.append(loaded); return selector
    generator(factory, planner).generate(request())
    env = planner.calls[0]["filtered_env"]
    assert [item.namingsql_name for item in env.naming_sql_selection] == ["FindCustomer", "FindCustomerRecent"]
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


def test_summary_field_with_aggregate_type_uses_summary_branch():
    planner = Planner(fetch=False)
    def fail(_): raise AssertionError("factory must not be called")
    summary_request = request(False).model_copy(update={"is_ab": True, "node": {
        "field_id": "sum", "tree_node_type": "field", "name": "total",
        "aggregate_type": "sum", "detail_field": "AMOUNT",
    }})
    result = generator(fail, planner).generate(summary_request)
    assert result.logic_type == "summary" and result.source.summary_type == "sum"
    assert not planner.calls


def test_default_filter_path_uses_expression_spec_text():
    class CapturingTargets:
        def __init__(self): self.calls = []
        def generate(self, **kwargs): self.calls.append(kwargs); return []
    targets, planner = CapturingTargets(), Planner(fetch=False)
    gen = ValueLogicGenerator(resource_loader=ResourceLoader(), llm_planner=planner,
        naming_sql_selector_factory=lambda loaded: (_ for _ in ()).throw(AssertionError()),
        resource_filter_target_generator=targets)
    gen.generate(request(False))
    assert targets.calls[0]["query"] == "ordinary"


def test_parent_sql_direct_field_mapping_requires_field_id():
    planner = Planner(fetch=False)
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"field_id": "log", "tree_node_type": "field", "name": "LOG_ID", "is_ab": True},
        "parent_node": {"data_source_type": "sql", "bo_name": "BB_BAK_TRANS"},
        "query": "direct BO field mapping",
    })
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(req)
    assert result.logic_type == "bo_field_mapping" and result.expression == "LOG_ID"
    assert not planner.calls


def test_parent_sql_node_without_field_id_falls_back_to_expression():
    planner = Planner(fetch=False)
    req = request(False).model_copy(update={
        "is_ab": True,
        "node": {"node_id": "log", "tree_node_type": "field", "name": "LOG_ID", "is_ab": True},
        "parent_node": {"data_source_type": "sql", "bo_name": "BB_BAK_TRANS"},
        "query": "direct BO field mapping",
    })
    result = generator(lambda loaded: (_ for _ in ()).throw(AssertionError()), planner).generate(req)
    assert result.logic_type == "expression"
    assert planner.calls


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
        resource_filter_target_generator=Targets(),
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
        "field_id": "normal-field", "tree_node_type": "field", "xml_name_property": {"xml_name": field}},
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
