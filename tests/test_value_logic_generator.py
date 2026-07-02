import pytest

from agent.context_manager.models import NamingSqlCandidate
from agent.models import ValueLogicRequest
from agent.naming_sql_selector import NamingSqlSelectResponse
from agent.planner.models import Plan
from agent.resource_manager.loader.resource_loader import ResourceLoader
from agent.value_logic_generator import ExpressionSpec, ValueLogicGenerator, requires_naming_sql
from tests.test_environment import sample_edsl_tree_payload


class Targets:
    def generate(self, **kwargs): return []


class Specs:
    def generate(self, *, request, node_info): return ExpressionSpec(nl=request.query)


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


def candidate(cid, name, rank):
    return NamingSqlCandidate(candidate_id=f"internal:{cid}", bo_name="BB_BAK_TRANS", naming_sql_id=cid,
        naming_sql_name=name, param_list=[{"param_name": "id", "data_type_name": "String"}],
        source="resource_registry", rank=rank)


def success():
    return NamingSqlSelectResponse(success=True, candidates=[candidate("a", "FindCustomer", 1),
        candidate("b", "FindCustomerRecent", 2)])


def request(route=True):
    return ValueLogicRequest(site_id="site1", project_id="project1", node_path="$.x",
        node={"node_id": "x", "name": "x", "reference_logic_area_id_list": ["area.1"]},
        parent_node={"data_source_type": "sql", "bo_name": "ParentBO"}, query="use naming sql" if route else "ordinary",
        structured_spec={"requires_naming_sql": route, "bo_name": "BB_BAK_TRANS"}, edsl_tree=sample_edsl_tree_payload())


def generator(factory, planner):
    return ValueLogicGenerator(resource_loader=ResourceLoader(), llm_planner=planner,
        naming_sql_selector_factory=factory, expression_spec_generator=Specs(),
        resource_filter_target_generator=Targets())


def test_non_naming_sql_route_does_not_construct_factory_and_regresses_ordinary_path():
    planner = Planner(fetch=False)
    def fail(_): raise AssertionError("factory must not be called")
    result = generator(fail, planner).generate(request(False))
    assert result.expression == '"ok"' and planner.calls[0]["filtered_env"].naming_sql_selection is None


def test_route_factory_receives_current_loaded_resource_and_request_fields():
    planner, seen = Planner(), []
    selector = Selector(success())
    def factory(loaded): seen.append(loaded); return selector
    generator(factory, planner).generate(request())
    call = selector.calls[0]
    assert seen and call.site_id == "site1" and call.project_id == "project1" and call.json_path == "$.x"
    assert call.target_bo_name == "BB_BAK_TRANS" and call.parent_bo_hint == "ParentBO"
    assert call.target_logic_area_id_list == ["area.1"] and call.top_k == 5


def test_selector_failure_is_stable_and_stops_planner():
    planner = Planner()
    selector = Selector(NamingSqlSelectResponse(success=False, failure_reason="NO_CANDIDATES\nprivate"))
    with pytest.raises(ValueError, match=r"NAMING_SQL_SELECTION_FAILED reason=NO_CANDIDATES\?private"):
        generator(lambda loaded: selector, planner).generate(request())
    assert not planner.calls


def test_success_reaches_planner_with_all_top_k_and_without_narrowing_loaded_resource():
    planner, loaded_seen = Planner(), []
    selector = Selector(success())
    def factory(loaded): loaded_seen.append(loaded); return selector
    generator(factory, planner).generate(request())
    env = planner.calls[0]["filtered_env"]
    assert [item.naming_sql_name for item in env.naming_sql_selection.candidates] == ["FindCustomer", "FindCustomerRecent"]
    assert len(loaded_seen[0].bo_registry["BB_BAK_TRANS"].naming_sql_list) == 1


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
