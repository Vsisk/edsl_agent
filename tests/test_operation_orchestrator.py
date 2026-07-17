from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

import agent.operation_orchestration as public_api
from agent.operation_orchestration import (
    ExecuteOperationsResponse,
    GenerateOperationsResponse,
    NodeLocateCandidate,
    Operation,
    OperationActionAdapter,
    OperationExecutor,
    OperationGenerator,
    OperationLocator,
    OperationOrchestrator,
    OperationToolLoopRequest,
    OperationToolLoopResponse,
    build_node_index,
    is_valid_candidate,
    validate_and_sort_operations,
)


def _tree() -> dict[str, Any]:
    return {
        "node_id": "bill",
        "tree_node_type": "parent",
        "xml_name_property": {"xml_name": "BILL_INFO"},
        "children": [
            {
                "node_id": "acct-id",
                "tree_node_type": "simple_leaf",
                "xml_name_property": {"xml_name": "ACCT_ID"},
            }
        ],
    }


def test_default_facade_delegates_to_tool_loop_and_preserves_inputs() -> None:
    tree = _tree()
    original = deepcopy(tree)
    expected = OperationToolLoopResponse(
        success=True,
        target_tree={"node_id": "updated"},
        operations=[],
        tree_version=2,
    )

    class ToolLoop:
        request = None

        def run(self, request):
            self.request = request
            request.target_tree["poison"] = True
            return expected

    tool_loop = ToolLoop()
    actual = OperationOrchestrator(tool_loop=tool_loop).run(
        "multi task", tree, "site", "project", max_steps=8
    )

    assert actual is expected
    assert isinstance(tool_loop.request, OperationToolLoopRequest)
    assert tool_loop.request.query == "multi task"
    assert tool_loop.request.site_id == "site"
    assert tool_loop.request.project_id == "project"
    assert tool_loop.request.max_steps == 8
    assert tree == original


def test_tool_loop_cannot_be_combined_with_legacy_dependencies() -> None:
    for dependency in (
        {"generator": object()},
        {"locator": object()},
        {"executor": object()},
        {"action_adapter": object()},
    ):
        with pytest.raises(
            ValueError,
            match="^tool_loop cannot be combined with legacy dependencies$",
        ):
            OperationOrchestrator(tool_loop=object(), **dependency)


def test_facade_forwards_exact_requests_and_preserves_inputs_and_response() -> None:
    tree = _tree()
    original = deepcopy(tree)
    generated = [Operation(op_id="one", query="create", intent_type="create_node")]
    expected = ExecuteOperationsResponse(
        success=True, target_tree={"node_id": "done"}, operations=generated
    )

    class Generator:
        request = None

        def generate(self, request):
            self.request = request
            return GenerateOperationsResponse(operations=generated)

    class Executor:
        request = None

        def execute(self, request):
            self.request = request
            return expected

    generator, executor = Generator(), Executor()
    actual = OperationOrchestrator(generator=generator, executor=executor).run(
        "make it", tree, site_id="site", project_id="project"
    )

    assert actual is expected
    assert generator.request.query == "make it"
    assert generator.request.target_tree == original
    assert generator.request.target_tree is not tree
    assert executor.request.operations == generated
    assert executor.request.operations is not generated
    assert executor.request.target_tree == original
    assert executor.request.site_id == "site"
    assert executor.request.project_id == "project"
    assert tree == original


def test_explicit_executor_avoids_unused_default_dependencies(monkeypatch) -> None:
    import agent.operation_orchestration.orchestrator as module

    class Generator:
        def generate(self, request):
            return GenerateOperationsResponse(operations=[])

    class Executor:
        def execute(self, request):
            return ExecuteOperationsResponse(
                success=True, target_tree=request.target_tree, operations=[]
            )

    def forbidden():
        raise AssertionError("unused dependency constructed")

    monkeypatch.setattr(module, "OperationLocator", forbidden)
    monkeypatch.setattr(module, "OperationActionAdapter", forbidden)
    orchestrator = OperationOrchestrator(generator=Generator(), executor=Executor())

    assert orchestrator.run("noop", _tree()).success


@pytest.mark.parametrize(
    "conflicting",
    [
        {"locator": object()},
        {"action_adapter": object()},
        {"locator": object(), "action_adapter": object()},
    ],
)
def test_explicit_executor_rejects_locator_or_adapter_conflicts(conflicting) -> None:
    with pytest.raises(
        ValueError,
        match="^executor cannot be combined with locator or action_adapter$",
    ):
        OperationOrchestrator(executor=object(), **conflicting)


def test_default_executor_shares_the_chosen_locator_and_adapter() -> None:
    locator = object()
    adapter = object()

    orchestrator = OperationOrchestrator(
        generator=object(), locator=locator, action_adapter=adapter
    )

    assert orchestrator.executor._locator is locator
    assert orchestrator.executor._action_adapter is adapter


def test_generation_failure_returns_stable_private_tree_copy_without_secrets() -> None:
    tree = _tree()
    secret = "api-key-super-secret"

    class BrokenGenerator:
        def generate(self, request):
            request.target_tree["poison"] = True
            raise RuntimeError(f"gateway offline: {secret}")

    response = OperationOrchestrator(
        generator=BrokenGenerator(), executor=object()
    ).run("query", tree)

    assert response == ExecuteOperationsResponse(
        success=False,
        target_tree=tree,
        operations=[],
        error_message="operation generation failed",
    )
    assert response.target_tree is not tree
    assert "poison" not in tree
    assert secret not in response.error_message


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    @staticmethod
    def _candidate(tree: dict[str, Any], path: str):
        return next(item for item in build_node_index(tree).values() if item.jsonpath == path)

    @staticmethod
    def _node(tree: dict[str, Any], identity: str) -> dict[str, Any]:
        def visit(value):
            if isinstance(value, dict):
                if value.get("node_id") == identity or value.get("field_id") == identity:
                    return value
                for child in value.values():
                    found = visit(child)
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = visit(child)
                    if found is not None:
                        return found
            return None

        return visit(tree)

    def create_node(self, query, path, current):
        target = self._candidate(current, path)
        parent = self._node(current, target.node_id)
        name = next(
            (candidate for candidate in ("ACCT_INFO", "ACCT_ID", "AB_FIELD", "NEW_FIELD", "A", "B", "C") if query.startswith(candidate)),
            query.split()[0],
        )
        if name == "AB_FIELD":
            created_id = "field-amount"
            parent.setdefault("detail_fields", []).append(
                {"field_id": created_id, "xml_name_property": {"xml_name": "AMOUNT"}}
            )
        else:
            created_id = name.lower().replace("_", "-")
            node_type = "parent" if name in {"ACCT_INFO", "A"} else "simple_leaf"
            parent.setdefault("children", []).append(
                {
                    "node_id": created_id,
                    "tree_node_type": node_type,
                    "xml_name_property": {"xml_name": name},
                    **({"children": []} if node_type == "parent" else {}),
                }
            )
        self.calls.append(("create", target.node_id, None, None))
        return {"created_node_id": created_id, "target_tree": current}

    def modify_node(self, query, path, current, site_id=None, project_id=None):
        target = self._candidate(current, path)
        self._node(current, target.node_id)["modified"] = query
        self.calls.append(("modify", target.node_id, site_id, project_id))
        return {"target_tree": current}

    def generate_expression(self, query, path, current, site_id=None, project_id=None):
        target = self._candidate(current, path)
        self._node(current, target.node_id)["expression"] = query
        self.calls.append(("expression", target.node_id, site_id, project_id))
        return {"target_tree": current}

    def delete_node(self, path, current):
        target = self._candidate(current, path)
        parent_id = target.parent_node_id
        parent = self._node(current, parent_id)
        parent["children"] = [
            child for child in parent["children"] if child.get("node_id") != target.node_id
        ]
        self.calls.append(("delete", target.node_id, None, None))
        return {"parent_node_id": parent_id, "target_tree": current}


def _accept(payload, tree=None, selected="bill"):
    locator_calls = []

    def locate(query, intent, candidates):
        locator_calls.append((query, intent))
        candidate = next(item for item in candidates if item["node_id"] == selected)
        return {
            "selected_node_id": candidate["node_id"],
            "selected_jsonpath": candidate["jsonpath"],
            "confidence": "high",
            "reason": "scripted",
        }

    adapter = _RecordingAdapter()
    orchestrator = OperationOrchestrator(
        generator=OperationGenerator(llm_gateway=lambda *_: payload),
        executor=OperationExecutor(
            locator=OperationLocator(llm_gateway=locate), action_adapter=adapter
        ),
    )
    response = orchestrator.run(
        "acceptance", _tree() if tree is None else tree, "S", "P"
    )
    return response, locator_calls, adapter


@pytest.mark.parametrize(
    (
        "payload",
        "selected",
        "outputs",
        "targets",
        "final_ids",
        "expected_calls",
        "empty_tree",
    ),
    [
        ({"operations": [{"op_id": "x", "query": "NEW_FIELD", "intent_type": "create_node"}]}, "bill", ["new-field"], ["bill"], ["bill", "acct-id", "new-field"], [("create", "bill", None, None)], False),
        ({"operations": [{"op_id": "a", "query": "ACCT_INFO", "intent_type": "create_node"}, {"op_id": "b", "query": "ACCT_ID", "intent_type": "create_node", "depends_on": ["a"]}]}, "bill", ["acct-info", "acct-id"], ["bill", "acct-info"], ["bill", "acct-info", "acct-id"], [("create", "bill", None, None), ("create", "acct-info", None, None)], True),
        ({"operations": [{"op_id": "a", "query": "NEW_FIELD", "intent_type": "create_node"}, {"op_id": "b", "query": "formula", "intent_type": "generate_expression", "depends_on": ["a"]}]}, "bill", ["new-field", "new-field"], ["bill", "new-field"], ["bill", "acct-id", "new-field"], [("create", "bill", None, None), ("expression", "new-field", "S", "P")], False),
        ({"operations": [{"op_id": "x", "query": "rename", "intent_type": "modify_node"}]}, "acct-id", ["acct-id"], ["acct-id"], ["bill", "acct-id"], [("modify", "acct-id", "S", "P")], False),
        ({"operations": [{"op_id": "x", "query": "delete", "intent_type": "delete_node"}]}, "acct-id", ["bill"], ["acct-id"], ["bill"], [("delete", "acct-id", None, None)], False),
        ({"operations": [{"op_id": "a", "query": "A", "intent_type": "create_node"}, {"op_id": "b", "query": "B", "intent_type": "create_node", "depends_on": ["a"]}, {"op_id": "c", "query": "C", "intent_type": "create_node", "depends_on": ["a"]}]}, "bill", ["a", "b", "c"], ["bill", "a", "a"], ["bill", "acct-id", "a", "b", "c"], [("create", "bill", None, None), ("create", "a", None, None), ("create", "a", None, None)], False),
    ],
)
def test_real_components_accept_deterministic_operation_flows(
    payload, selected, outputs, targets, final_ids, expected_calls, empty_tree
) -> None:
    initial_tree = _tree()
    if empty_tree:
        initial_tree["children"] = []
    response, locator_calls, adapter = _accept(payload, tree=initial_tree, selected=selected)

    assert response.success, response.error_message
    assert [op.status for op in response.operations] == ["executed"] * len(outputs)
    assert [op.output_node_id for op in response.operations] == outputs
    assert [op.target_node_id for op in response.operations] == targets
    assert list(build_node_index(response.target_tree)) == final_ids
    assert len(locator_calls) == 1
    assert adapter.calls == expected_calls
    if expected_calls[-1][0] == "modify":
        assert _RecordingAdapter._node(response.target_tree, "acct-id")["modified"] == "rename"
    if expected_calls[-1][0] == "expression":
        assert _RecordingAdapter._node(response.target_tree, "new-field")["expression"] == "formula"
    if outputs == ["a", "b", "c"]:
        a = _RecordingAdapter._node(response.target_tree, "a")
        assert [child["node_id"] for child in a["children"]] == ["b", "c"]
        assert response.operations[0].query != "A"


def test_real_components_support_ab_field_id_output() -> None:
    tree = {
        "node_id": "ab",
        "tree_node_type": "ab_pivot_table",
        "detail_fields": [],
    }
    payload = {"operations": [{"op_id": "f", "query": "AB_FIELD", "intent_type": "create_node"}]}

    response, locator_calls, adapter = _accept(payload, tree=tree, selected="ab")

    assert response.success
    assert response.operations[0].output_node_id == "field-amount"
    field = build_node_index(response.target_tree)["field-amount"]
    assert field.identity_field == "field_id"
    assert field.field_slot == "detail_fields"
    assert len(locator_calls) == 1
    assert adapter.calls == [("create", "ab", None, None)]


def test_public_exports_are_explicit_and_importable() -> None:
    expected = {
        "CreateNodeInput",
        "DeleteNodeInput",
        "ExecuteOperationsRequest",
        "ExecuteOperationsResponse",
        "FinishInput",
        "GenerateExpressionInput",
        "GenerateOperationsRequest",
        "GenerateOperationsResponse",
        "IntentType",
        "LocateOperationRequest",
        "LocateOperationResponse",
        "ModifyNodeInput",
        "NodeLocateCandidate",
        "Operation",
        "OperationActionAdapter",
        "OperationExecutor",
        "OperationGenerator",
        "OperationLocator",
        "OperationOrchestrator",
        "OperationStatus",
        "OperationToolLoop",
        "OperationToolLoopRequest",
        "OperationToolLoopResponse",
        "OperationToolRegistry",
        "OperationToolRuntime",
        "OperationToolSpec",
        "SearchNodesInput",
        "ToolCallTrace",
        "ToolDecision",
        "ToolExecutionContext",
        "build_node_index",
        "is_valid_candidate",
        "validate_and_sort_operations",
    }

    assert set(public_api.__all__) == expected
    assert len(public_api.__all__) == len(expected)
    for name in expected:
        assert getattr(public_api, name) is not None
