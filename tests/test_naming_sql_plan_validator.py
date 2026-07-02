import pytest

from agent.context_manager.models import NamingSqlCandidate, NamingSqlSelectionConstraints
from agent.naming_sql_selector import NamingSqlSelectResponse, validate_naming_sql_plan
from agent.planner.models import Plan


def response(*candidates, constraints=None):
    return NamingSqlSelectResponse(success=True, candidates=list(candidates), selection_constraints=constraints)


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


def constraints(ids, bos=("Customer",), max_candidates=None):
    return NamingSqlSelectionConstraints(allowed_naming_sql_ids=list(ids), allowed_bo_names=list(bos),
        max_candidates=max_candidates if max_candidates is not None else len(ids))


def test_constraints_limit_fetch_to_permitted_top_k_candidate():
    selection = response(candidate("a", "FindCustomer"), candidate("b", "FindByEmail", ("email",), 2),
        constraints=constraints(["a"]))
    validate_naming_sql_plan(plan("FindCustomer"), selection)
    with pytest.raises(ValueError, match="NAMING_SQL_OUTSIDE_CONSTRAINTS"):
        validate_naming_sql_plan(plan("FindByEmail", "email"), selection)


def test_constraints_reject_wrong_bo_and_invalid_ids_before_plan_walk():
    a = candidate("a", "FindCustomer")
    invalid = [constraints(["missing"]), constraints(["a"], bos=("Other",))]
    cyclic = Plan.model_construct(nodes=[])
    cyclic.nodes.append(cyclic)
    for item in invalid:
        with pytest.raises(ValueError, match="NAMING_SQL_INVALID_CONSTRAINTS"):
            validate_naming_sql_plan(cyclic, response(a, constraints=item))


def test_max_candidates_may_cover_top_k_while_allowed_ids_are_narrower():
    candidates = [candidate(chr(97 + index), f"Find{index}", rank=index + 1) for index in range(5)]
    selection = response(*candidates, constraints=constraints(["a"], max_candidates=5))

    validate_naming_sql_plan(plan("Find0"), selection)
    with pytest.raises(ValueError, match="NAMING_SQL_OUTSIDE_CONSTRAINTS"):
        validate_naming_sql_plan(plan("Find1"), selection)


def test_invalid_max_and_allowed_id_count_are_rejected_before_plan_walk():
    candidates = [candidate("a", "Find0"), candidate("b", "Find1", rank=2)]
    invalid = [constraints(["a"], max_candidates=3), constraints(["a", "b"], max_candidates=1)]
    cyclic = Plan.model_construct(nodes=[])
    cyclic.nodes.append(cyclic)
    for item in invalid:
        with pytest.raises(ValueError, match="NAMING_SQL_INVALID_CONSTRAINTS"):
            validate_naming_sql_plan(cyclic, response(*candidates, constraints=item))
    nonpositive = response(*candidates, constraints=constraints(["a"], max_candidates=1))
    nonpositive.selection_constraints.max_candidates = 0
    with pytest.raises(ValueError, match="NAMING_SQL_INVALID_CONSTRAINTS"):
        validate_naming_sql_plan(cyclic, nonpositive)


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
