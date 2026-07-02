import pytest

from agent.context_manager.models import NamingSqlCandidate
from agent.naming_sql_selector import NamingSqlSelectResponse, validate_naming_sql_plan
from agent.planner.models import Plan


def response(*candidates):
    return NamingSqlSelectResponse(success=True, candidates=list(candidates))


def candidate(cid, name, params=("id",), rank=1):
    return NamingSqlCandidate(candidate_id=cid, bo_name="Customer", naming_sql_id=cid,
        naming_sql_name=name, param_list=[{"param_name": p, "data_type_name": "String"} for p in params],
        source="resource_registry", rank=rank)


def plan(name="FindCustomer", param="id"):
    return Plan.model_validate({"nodes": [{"type": "fetch_one", "name": name,
        "params": [{"name": param, "value": {"type": "literal", "value": "x"}}]}]})


def test_planner_may_choose_any_top_k_candidate():
    validate_naming_sql_plan(plan("FindByEmail", "email"), response(
        candidate("a", "FindCustomer"), candidate("b", "FindByEmail", ("email",), 2)))


def test_rejects_fetch_name_outside_top_k():
    with pytest.raises(ValueError, match="NAMING_SQL_OUTSIDE_TOP_K"):
        validate_naming_sql_plan(plan("Sibling"), response(candidate("a", "FindCustomer")))


def test_rejects_unknown_parameter_but_not_binding_source():
    selection = response(candidate("a", "FindCustomer"))
    with pytest.raises(ValueError, match="NAMING_SQL_UNKNOWN_PARAM"):
        validate_naming_sql_plan(plan(param="other"), selection)
    validate_naming_sql_plan(Plan.model_validate({"nodes": [{"type": "fetch_one", "name": "FindCustomer",
        "params": [{"name": "id", "value": {"type": "context_path", "path": "$ctx$.anything"}}]}]}), selection)


def test_duplicate_candidate_names_are_rejected_as_ambiguous():
    with pytest.raises(ValueError, match="NAMING_SQL_CANDIDATE_AMBIGUOUS"):
        validate_naming_sql_plan(plan(), response(candidate("a", "FindCustomer"), candidate("b", "FindCustomer", rank=2)))


def test_plan_without_fetch_is_rejected():
    plain = Plan.model_validate({"nodes": [{"type": "return", "value": {"type": "literal", "value": 1}}]})
    with pytest.raises(ValueError, match="NAMING_SQL_NOT_USED"):
        validate_naming_sql_plan(plain, response(candidate("a", "FindCustomer")))


def test_nested_and_multiple_top_k_fetches_are_validated():
    nested = Plan.model_validate({"nodes": [{"type": "return", "value": {"type": "call", "name": "IF", "args": [
        {"type": "literal", "value": True},
        {"type": "fetch_one", "name": "FindCustomer", "params": [{"name": "id", "value": {"type": "literal", "value": 1}}]},
        {"type": "fetch", "name": "FindByEmail", "params": [{"name": "email", "value": {"type": "literal", "value": "a"}}]},
    ]}}]})
    validate_naming_sql_plan(nested, response(candidate("a", "FindCustomer"), candidate("b", "FindByEmail", ("email",), 2)))


def test_cyclic_plan_is_rejected_with_stable_complexity_error():
    cyclic = Plan.model_construct(nodes=[])
    cyclic.nodes.append(cyclic)
    with pytest.raises(ValueError, match="NAMING_SQL_PLAN_TOO_COMPLEX"):
        validate_naming_sql_plan(cyclic, response(candidate("a", "FindCustomer")))
