from copy import deepcopy

import pytest

from agent.operation_orchestration.executor import OperationExecutor
from agent.operation_orchestration.models import (
    ExecuteOperationsRequest,
    LocateOperationResponse,
    Operation,
)


def tree():
    return {
        "root": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [
                {"node_id": "a", "tree_node_type": "simple_leaf"},
                {"node_id": "b", "tree_node_type": "simple_leaf"},
            ],
        }
    }


class RecordingLocator:
    def __init__(self, *, targets=None, failure=None):
        self.targets = targets or {}
        self.failure = failure
        self.calls = []

    def locate(self, request):
        self.calls.append(deepcopy(request))
        operation = request.operation.model_copy(deep=True)
        if self.failure:
            operation.status = "failed"
            operation.error_message = self.failure
            return LocateOperationResponse(
                success=False, operation=operation, error_message=self.failure
            )
        node_id, path = self.targets.get(operation.op_id, ("root", "$.root"))
        operation.target_node_id = node_id
        operation.target_jsonpath = path
        operation.status = "located"
        return LocateOperationResponse(success=True, operation=operation)


class RecordingAdapter:
    def __init__(self, actions=None):
        self.actions = actions or {}
        self.calls = []

    def _run(self, intent, query, path, current, site_id=None, project_id=None):
        self.calls.append((intent, query, path, site_id, project_id, deepcopy(current)))
        action = self.actions.get(query)
        if isinstance(action, Exception):
            raise action
        if callable(action):
            return action(deepcopy(current), path)
        updated = deepcopy(current)
        if intent == "create_node":
            created_id = f"created-{query}"
            updated["root"]["children"].append(
                {"node_id": created_id, "tree_node_type": "simple_leaf"}
            )
            return {"created_node_id": created_id, "target_tree": updated}
        if intent == "delete_node":
            updated["root"]["children"] = [
                node for node in updated["root"]["children"] if node["node_id"] != "a"
            ]
            return {"parent_node_id": "root", "target_tree": updated}
        return {"target_tree": updated}

    def create_node(self, query, path, current):
        return self._run("create_node", query, path, current)

    def modify_node(self, query, path, current, site_id=None, project_id=None):
        return self._run("modify_node", query, path, current, site_id, project_id)

    def generate_expression(self, query, path, current, site_id=None, project_id=None):
        return self._run("generate_expression", query, path, current, site_id, project_id)

    def delete_node(self, path, current):
        return self._run("delete_node", "delete", path, current)


def op(op_id, intent="modify_node", *, depends_on=None, target_from=None, query=None):
    return Operation(
        op_id=op_id,
        query=query or op_id,
        intent_type=intent,
        depends_on=depends_on or [],
        target_from=target_from,
    )


def execute(operations, *, locator=None, adapter=None, target_tree=None, **ids):
    return OperationExecutor(locator=locator, action_adapter=adapter).execute(
        ExecuteOperationsRequest(
            operations=operations, target_tree=target_tree or tree(), **ids
        )
    )


def test_executes_topologically_but_returns_operations_in_input_order_and_locates_only_roots():
    operations = [op("child", depends_on=["root-op"]), op("root-op")]
    locator = RecordingLocator()
    adapter = RecordingAdapter()

    response = execute(operations, locator=locator, adapter=adapter)

    assert response.success
    assert [call[1] for call in adapter.calls] == ["root-op", "child"]
    assert [operation.op_id for operation in response.operations] == ["child", "root-op"]
    assert [operation.status for operation in response.operations] == ["executed", "executed"]
    assert [call.operation.op_id for call in locator.calls] == ["root-op"]
    assert response.operations[0].target_node_id == "root"


def test_reuses_valid_prelocated_root_without_calling_locator():
    operation = op("ready")
    operation.status = "located"
    operation.target_node_id = "a"
    operation.target_jsonpath = "$.root.children[0]"

    class ForbiddenLocator:
        def locate(self, request):
            raise AssertionError("valid prelocated operation must not call locator")

    response = execute(
        [operation], locator=ForbiddenLocator(), adapter=RecordingAdapter()
    )

    assert response.success
    assert response.operations[0].status == "executed"
    assert response.operations[0].output_node_id == "a"


@pytest.mark.parametrize(
    ("intent", "node_id", "path", "located_target"),
    [
        ("modify_node", "missing", "$.root.children[0]", ("a", "$.root.children[0]")),
        ("modify_node", "a", "$.root.children[1]", ("a", "$.root.children[0]")),
        ("create_node", "a", "$.root.children[0]", ("root", "$.root")),
    ],
)
def test_stale_or_incapable_prelocated_root_falls_back_to_locator(
    intent, node_id, path, located_target
):
    operation = op("retry", intent=intent)
    operation.status = "located"
    operation.target_node_id = node_id
    operation.target_jsonpath = path
    locator = RecordingLocator(targets={"retry": located_target})

    response = execute([operation], locator=locator, adapter=RecordingAdapter())

    assert response.success
    assert len(locator.calls) == 1
    assert response.operations[0].target_node_id == located_target[0]


def test_fanout_and_multiple_dependencies_use_selected_upstream_output_without_locator_calls():
    operations = [
        op("a", intent="create_node"),
        op("b", depends_on=["a"]),
        op("c", depends_on=["a"]),
        op("d", depends_on=["b", "c"], target_from="c"),
    ]
    locator = RecordingLocator()
    adapter = RecordingAdapter()

    response = execute(operations, locator=locator, adapter=adapter)

    assert response.success
    assert len(locator.calls) == 1
    calls = {call[1]: call for call in adapter.calls}
    assert calls["b"][2] == "$.root.children[2]"
    assert calls["c"][2] == "$.root.children[2]"
    assert calls["d"][2] == "$.root.children[2]"


def test_rebuilds_index_after_each_success_so_shifted_path_is_current():
    operations = [
        op("remove", intent="delete_node"),
        op("change", depends_on=["remove"]),
    ]
    locator = RecordingLocator(targets={"remove": ("a", "$.root.children[0]")})
    adapter = RecordingAdapter()

    response = execute(operations, locator=locator, adapter=adapter)

    assert response.success
    assert adapter.calls[1][2] == "$.root"
    assert response.operations[0].output_node_id == "root"


def test_forwards_context_and_uses_exact_dispatch_methods():
    operations = [
        op("modify", query="modify"),
        op("expression", intent="generate_expression", query="expression"),
    ]
    locator = RecordingLocator(
        targets={
            "modify": ("a", "$.root.children[0]"),
            "expression": ("b", "$.root.children[1]"),
        }
    )
    adapter = RecordingAdapter()

    response = execute(
        operations,
        locator=locator,
        adapter=adapter,
        site_id="site",
        project_id="project",
    )

    assert response.success
    assert [(c[0], c[3], c[4]) for c in adapter.calls] == [
        ("modify_node", "site", "project"),
        ("generate_expression", "site", "project"),
    ]
    assert [operation.output_node_id for operation in response.operations] == ["a", "b"]


def test_supports_ab_field_id_as_canonical_dependency_output():
    target = {
        "node_id": "ab",
        "tree_node_type": "ab_single_mapping_table",
        "detail_fields": [
            {"field_id": "field-1", "xml_name_property": {"xml_name": "F"}}
        ],
    }
    operations = [
        op("expression", intent="generate_expression"),
        op("next", intent="generate_expression", depends_on=["expression"]),
    ]
    locator = RecordingLocator(targets={"expression": ("field-1", "$.detail_fields[0]")})
    adapter = RecordingAdapter()

    response = execute(operations, locator=locator, adapter=adapter, target_tree=target)

    assert response.success
    assert response.operations[0].output_node_id == "field-1"
    assert adapter.calls[1][2] == "$.detail_fields[0]"


@pytest.mark.parametrize(
    "operations",
    [
        [op("same"), op("same")],
        [op("a", depends_on=["missing"])],
        [op("a", depends_on=["b"]), op("b", depends_on=["a"])],
    ],
)
def test_graph_errors_happen_before_external_calls_and_preserve_copied_inputs(operations):
    operations[0].status = "located"
    locator = RecordingLocator()
    adapter = RecordingAdapter()
    original_tree = tree()

    response = execute(operations, locator=locator, adapter=adapter, target_tree=original_tree)

    assert not response.success
    assert response.error_message.startswith("operation graph validation failed:")
    assert response.target_tree == original_tree
    assert response.target_tree is not original_tree
    assert response.operations[0].status == "located"
    assert locator.calls == [] and adapter.calls == []


def test_initial_index_failure_clears_stale_output_as_runtime_failure():
    operation = op("retry")
    operation.output_node_id = "stale-output"
    duplicate_tree = {
        "items": [
            {"node_id": "duplicate", "tree_node_type": "simple_leaf"},
            {"node_id": "duplicate", "tree_node_type": "simple_leaf"},
        ]
    }
    locator = RecordingLocator()
    adapter = RecordingAdapter()

    response = execute(
        [operation], locator=locator, adapter=adapter, target_tree=duplicate_tree
    )

    assert not response.success
    assert response.operations[0].status == "failed"
    assert response.operations[0].output_node_id is None
    assert "duplicate node_id" in response.error_message
    assert locator.calls == [] and adapter.calls == []


def test_initial_index_failure_normalizes_unvisited_tail_runtime_state():
    first = op("first")
    first.status = "executed"
    first.output_node_id = "old-first"
    tail = op("tail")
    tail.status = "failed"
    tail.target_node_id = "old-target"
    tail.target_jsonpath = "$.old"
    tail.output_node_id = "old-output"
    tail.error_message = "old-error"
    operations = [first, tail]
    before = deepcopy(operations)
    duplicate_tree = {
        "items": [
            {"node_id": "duplicate", "tree_node_type": "simple_leaf"},
            {"node_id": "duplicate", "tree_node_type": "simple_leaf"},
        ]
    }

    response = execute(operations, target_tree=duplicate_tree)

    assert not response.success
    assert response.operations[0].status == "failed"
    assert response.operations[0].output_node_id is None
    assert response.operations[1].status == "pending"
    assert response.operations[1].target_node_id is None
    assert response.operations[1].target_jsonpath is None
    assert response.operations[1].output_node_id is None
    assert response.operations[1].error_message is None
    assert operations == before


def test_locator_failure_propagates_and_stops():
    response = execute(
        [op("a")],
        locator=RecordingLocator(failure="cannot locate target"),
        adapter=RecordingAdapter(),
    )

    assert not response.success
    assert response.error_message == "cannot locate target"
    assert response.operations[0].status == "failed"
    assert response.operations[0].error_message == "cannot locate target"


@pytest.mark.parametrize("failure_mode", ["locator", "adapter", "postcondition"])
def test_failed_retry_clears_stale_output_node_id(failure_mode):
    operation = op("retry")
    operation.output_node_id = "stale-output"

    if failure_mode == "locator":
        locator = RecordingLocator(failure="cannot locate target")
        adapter = RecordingAdapter()
    elif failure_mode == "adapter":
        locator = RecordingLocator(targets={"retry": ("a", "$.root.children[0]")})
        adapter = RecordingAdapter(actions={"retry": RuntimeError("boom")})
    else:
        locator = RecordingLocator(targets={"retry": ("a", "$.root.children[0]")})
        invalid_tree = {
            "root": {
                "node_id": "root",
                "tree_node_type": "parent",
                "children": [{"node_id": "b", "tree_node_type": "simple_leaf"}],
            }
        }
        adapter = RecordingAdapter(
            actions={"retry": lambda current, path: {"target_tree": invalid_tree}}
        )

    response = execute([operation], locator=locator, adapter=adapter)

    assert not response.success
    assert response.operations[0].status == "failed"
    assert response.operations[0].output_node_id is None


@pytest.mark.parametrize(
    ("locator", "message"),
    [
        (RecordingLocator(targets={"a": ("a", "$.wrong")}), "target fields"),
        (RecordingLocator(targets={"a": ("a", "$.root.children[0]")}), "valid candidate"),
    ],
)
def test_rejects_inconsistent_location_and_invalid_create_target(locator, message):
    operation = op("a", intent="create_node")
    response = execute([operation], locator=locator, adapter=RecordingAdapter())

    assert not response.success
    assert message in response.error_message


def test_blank_create_output_fails_before_dependent_without_calling_it():
    operations = [op("a", intent="create_node"), op("b", depends_on=["a"])]
    locator = RecordingLocator()
    adapter = RecordingAdapter()
    adapter.actions["a"] = lambda current, path: {
        "created_node_id": " ",
        "target_tree": current,
    }

    response = execute(operations, locator=locator, adapter=adapter)

    assert not response.success
    assert response.operations[0].status == "failed"
    assert "output" in response.error_message
    assert [call[1] for call in adapter.calls] == ["a"]


def test_missing_output_in_candidate_tree_does_not_leak_candidate_tree():
    candidate = {
        "root": {
            "node_id": "root",
            "tree_node_type": "parent",
            "children": [{"node_id": "b", "tree_node_type": "simple_leaf"}],
        },
        "poison": True,
    }
    adapter = RecordingAdapter(
        actions={"a": lambda current, path: {"target_tree": candidate}}
    )
    original = tree()

    response = execute(
        [op("a")], locator=RecordingLocator(targets={"a": ("a", "$.root.children[0]")}),
        adapter=adapter, target_tree=original
    )

    assert not response.success
    assert "output" in response.error_message
    assert response.target_tree == original
    assert "poison" not in response.target_tree


def test_adapter_exception_fails_fast_with_prior_success_and_partial_tree_only():
    adapter = RecordingAdapter(actions={"second": RuntimeError("boom")})
    operations = [
        op("first", intent="create_node", query="first"),
        op("second", query="second"),
        op("later", query="later"),
    ]
    locator = RecordingLocator(
        targets={"first": ("root", "$.root"), "second": ("a", "$.root.children[0]")}
    )
    request = ExecuteOperationsRequest(operations=operations, target_tree=tree())
    before = request.model_copy(deep=True)

    response = OperationExecutor(locator=locator, action_adapter=adapter).execute(request)

    assert not response.success
    assert [operation.status for operation in response.operations] == [
        "executed", "failed", "pending"
    ]
    assert response.operations[0].output_node_id == "created-first"
    assert response.operations[1].error_message == "operation second failed: boom"
    assert response.error_message == response.operations[1].error_message
    assert "created-first" in str(response.target_tree)
    assert [call[1] for call in adapter.calls] == ["first", "second"]
    assert request == before


def test_failure_leaves_all_unvisited_operations_in_normalized_pending_state():
    first = op("first")
    incoming_executed = op("incoming-executed")
    incoming_executed.status = "executed"
    incoming_executed.target_node_id = "a"
    incoming_executed.target_jsonpath = "$.root.children[0]"
    incoming_executed.output_node_id = "old-executed-output"
    incoming_executed.error_message = "old-executed-error"
    incoming_failed = op("incoming-failed")
    incoming_failed.status = "failed"
    incoming_failed.target_node_id = "b"
    incoming_failed.target_jsonpath = "$.root.children[1]"
    incoming_failed.output_node_id = "old-failed-output"
    incoming_failed.error_message = "old-failed-error"
    incoming_located = op("incoming-located")
    incoming_located.status = "located"
    incoming_located.target_node_id = "b"
    incoming_located.target_jsonpath = "$.root.children[1]"
    incoming_located.output_node_id = "old-located-output"
    incoming_located.error_message = "old-located-error"
    operations = [first, incoming_executed, incoming_failed, incoming_located]
    before = deepcopy(operations)
    locator = RecordingLocator(targets={"first": ("a", "$.root.children[0]")})
    adapter = RecordingAdapter(actions={"first": RuntimeError("boom")})

    response = execute(operations, locator=locator, adapter=adapter)

    assert not response.success
    assert response.operations[0].status == "failed"
    executed_tail, failed_tail, located_tail = response.operations[1:]
    for tail in (executed_tail, failed_tail, located_tail):
        assert tail.status == "pending"
        assert tail.output_node_id is None
        assert tail.error_message is None
    assert (executed_tail.target_node_id, executed_tail.target_jsonpath) == (None, None)
    assert (failed_tail.target_node_id, failed_tail.target_jsonpath) == (None, None)
    assert (located_tail.target_node_id, located_tail.target_jsonpath) == (
        "b",
        "$.root.children[1]",
    )
    assert operations == before


def test_mutating_adapter_input_then_raising_cannot_leak_attempted_changes():
    original = tree()

    class MutateThenRaise:
        def modify_node(self, query, path, current, site_id=None, project_id=None):
            current["poison"] = "raised"
            current["root"]["children"].clear()
            raise RuntimeError("boom")

    response = execute(
        [op("a")],
        locator=RecordingLocator(targets={"a": ("a", "$.root.children[0]")}),
        adapter=MutateThenRaise(),
        target_tree=original,
    )

    assert not response.success
    assert response.target_tree == original
    assert "poison" not in response.target_tree


def test_mutating_adapter_input_then_returning_invalid_output_cannot_leak_changes():
    original = tree()

    class MutateThenInvalid:
        def modify_node(self, query, path, current, site_id=None, project_id=None):
            current["poison"] = "invalid"
            current["root"]["children"] = []
            return {"target_tree": current}

    response = execute(
        [op("a")],
        locator=RecordingLocator(targets={"a": ("a", "$.root.children[0]")}),
        adapter=MutateThenInvalid(),
        target_tree=original,
    )

    assert not response.success
    assert "output node ID is absent" in response.error_message
    assert response.target_tree == original
    assert "poison" not in response.target_tree


def test_empty_operations_succeed_with_deep_copied_tree():
    original = tree()
    response = execute([], target_tree=original)

    assert response.success and response.error_message is None
    assert response.operations == []
    assert response.target_tree == original
    assert response.target_tree is not original
