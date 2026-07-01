import copy
import unittest

from agent.naming_sql_selector.models import (
    NamingSqlSelectionResult, ParamBinding, ParamBindingPlan, SelectedNamingSql,
)
from agent.naming_sql_selector.plan_validator import validate_naming_sql_plan
from agent.planner.models import Plan


def selection(status="selected", selected=True):
    chosen = SelectedNamingSql(
        naming_sql_id="ns.1", sql_name="FindCustomer", score=1.0,
        binding_plan=ParamBindingPlan(bindings=[
            ParamBinding(param_name="customer_id", source_ref="$ctx$.customerId", confidence=.9, reason="exact"),
            ParamBinding(param_name="site", source_ref="$ctx$.site", confidence=.8, reason="scope"),
        ], is_complete=True),
    ) if selected else None
    return NamingSqlSelectionResult(status=status, selected_bo="Customer", selected=chosen, review_mode="not_required")


def fetch(name="FindCustomer", params=None, kind="fetch"):
    if params is None:
        params = [
            {"name": "customer_id", "value": {"type": "context_path", "path": "$ctx$.customerId"}},
            {"name": "site", "value": {"type": "context_path", "path": "$ctx$.site"}},
        ]
    return {"type": kind, "name": name, "params": params}


class NamingSqlPlanValidatorTest(unittest.TestCase):
    def assert_code(self, code, nodes, result=None):
        with self.assertRaisesRegex(ValueError, code):
            validate_naming_sql_plan(Plan.model_validate({"nodes": nodes}), result or selection())

    def test_accepts_fetch_and_fetch_one(self):
        for kind in ("fetch", "fetch_one"):
            validate_naming_sql_plan(Plan.model_validate({"nodes": [fetch(kind=kind)]}), selection())

    def test_rejects_wrong_sql_and_no_fetch(self):
        self.assert_code("NAMING_SQL_RESELECTED", [fetch(name="Other")])
        self.assert_code("NAMING_SQL_NOT_USED", [{"type": "literal", "value": 1}])

    def test_rejects_changed_param_set(self):
        valid = fetch()["params"]
        for params in (valid[:1], valid + [valid[0]], list(reversed(valid)), [valid[0], valid[0]]):
            self.assert_code("NAMING_SQL_PARAM_SET_CHANGED", [fetch(params=params)])

    def test_rejects_changed_binding_or_value_type(self):
        changed = copy.deepcopy(fetch()["params"])
        changed[0]["value"]["path"] = "$ctx$.other"
        self.assert_code("NAMING_SQL_BINDING_CHANGED", [fetch(params=changed)])
        literal = copy.deepcopy(fetch()["params"])
        literal[0]["value"] = {"type": "literal", "value": "$ctx$.customerId"}
        self.assert_code("NAMING_SQL_BINDING_CHANGED", [fetch(params=literal)])

    def test_traverses_nested_call_logical_and_def(self):
        nested = {"type": "def", "name": "x", "value": {"type": "call", "name": "IF", "args": [
            {"type": "logical", "op": "and", "items": [
                {"type": "compare", "op": "==", "left": fetch(), "right": {"type": "literal", "value": 1}},
                {"type": "literal", "value": True},
            ]}, {"type": "literal", "value": 1}
        ]}}
        validate_naming_sql_plan(Plan.model_validate({"nodes": [nested]}), selection())

    def test_allows_multiple_exact_uses(self):
        validate_naming_sql_plan(Plan.model_validate({"nodes": [fetch(), fetch(kind="fetch_one")]}), selection())

    def test_requires_completed_selection(self):
        self.assert_code("NAMING_SQL_REVIEW_REQUIRED", [fetch()], selection("needs_review", False))

    def test_does_not_mutate_inputs(self):
        plan = Plan.model_validate({"nodes": [fetch()]}); result = selection()
        before_plan = plan.model_dump(); before_result = result.model_dump()
        validate_naming_sql_plan(plan, result)
        self.assertEqual(before_plan, plan.model_dump()); self.assertEqual(before_result, result.model_dump())


if __name__ == "__main__": unittest.main()
