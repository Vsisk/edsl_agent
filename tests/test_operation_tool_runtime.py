from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from agent.operation_orchestration.runtime import OperationToolRuntime


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
                "annotation": "account identifier",
            }
        ],
    }


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def create_node(self, query: str, path: str, tree: dict[str, Any]):
        assert path == "$"
        tree["children"].append(
            {
                "node_id": "amount",
                "tree_node_type": "simple_leaf",
                "xml_name_property": {"xml_name": "AMOUNT"},
            }
        )
        self.calls.append(("create_node", query, path))
        return {"created_node_id": "amount", "target_tree": tree}

    def modify_node(
        self,
        query: str,
        path: str,
        tree: dict[str, Any],
        site_id: str | None = None,
        project_id: str | None = None,
    ):
        tree["children"][0]["annotation"] = query
        self.calls.append(("modify_node", query, path))
        return {"target_tree": tree}

    def generate_expression(
        self,
        query: str,
        path: str,
        tree: dict[str, Any],
        site_id: str | None = None,
        project_id: str | None = None,
    ):
        target = next(
            child for child in tree["children"] if child["node_id"] in path or child["node_id"] == "amount"
        )
        target["data_expression"] = {"expression": query}
        self.calls.append(("generate_expression", query, path))
        return {"target_tree": tree}

    def delete_node(self, path: str, tree: dict[str, Any]):
        target = tree["children"].pop(0)
        self.calls.append(("delete_node", target["node_id"], path))
        return {"parent_node_id": "bill", "target_tree": tree}


def _search(runtime: OperationToolRuntime, intent: str, query: str = "account"):
    return runtime.execute(
        "search_nodes",
        {"query": query, "intent_type": intent, "limit": 20},
    )


def _target_args(candidate: dict[str, Any], query: str = "change") -> dict[str, Any]:
    return {
        "target_node_id": candidate["node_id"],
        "target_jsonpath": candidate["jsonpath"],
        "candidate_version": candidate["candidate_version"],
        "query": query,
    }


def test_runtime_registers_only_phase_one_mapping_content_tools() -> None:
    runtime = OperationToolRuntime(_tree(), action_adapter=_RecordingAdapter())

    assert runtime.registry.names() == [
        "search_nodes",
        "create_node",
        "modify_node",
        "generate_expression",
        "delete_node",
        "finish",
    ]
    assert "switch_tree" not in runtime.registry.names()


def test_search_filters_by_intent_and_authorizes_current_tree_version() -> None:
    runtime = OperationToolRuntime(_tree(), action_adapter=_RecordingAdapter())

    result = _search(runtime, "generate_expression")

    assert result["version"] == 0
    assert [candidate["node_id"] for candidate in result["candidates"]] == ["acct-id"]
    assert result["candidates"][0]["candidate_version"] == 0
    assert result["candidates"][0]["identity_field"] == "node_id"


def test_mutation_requires_an_exact_authorized_search_candidate() -> None:
    runtime = OperationToolRuntime(_tree(), action_adapter=_RecordingAdapter())
    args = {
        "target_node_id": "acct-id",
        "target_jsonpath": "$.children[0]",
        "candidate_version": 0,
        "query": "rename",
    }

    with pytest.raises(ValueError, match="authorized search candidate"):
        runtime.execute("modify_node", args)

    candidate = next(
        candidate
        for candidate in _search(runtime, "modify_node")["candidates"]
        if candidate["node_id"] == "acct-id"
    )
    forged = _target_args(candidate)
    forged["target_jsonpath"] = "$"
    with pytest.raises(ValueError, match="authorized search candidate"):
        runtime.execute("modify_node", forged)


def test_successful_mutation_commits_reindexes_and_invalidates_old_grants() -> None:
    adapter = _RecordingAdapter()
    runtime = OperationToolRuntime(_tree(), action_adapter=adapter)
    old_modify = next(
        candidate
        for candidate in _search(runtime, "modify_node")["candidates"]
        if candidate["node_id"] == "acct-id"
    )
    parent = _search(runtime, "create_node", "bill")["candidates"][0]

    created = runtime.execute("create_node", _target_args(parent, "add amount"))

    assert created["created_node_id"] == "amount"
    assert created["version"] == 1
    assert runtime.version == 1
    assert runtime.tree["children"][-1]["node_id"] == "amount"
    assert runtime.operations[0].intent_type == "create_node"
    assert runtime.operations[0].status == "executed"

    with pytest.raises(ValueError, match="authorized search candidate"):
        runtime.execute("modify_node", _target_args(old_modify))

    expression_candidates = _search(runtime, "generate_expression", "amount")[
        "candidates"
    ]
    assert [candidate["node_id"] for candidate in expression_candidates] == [
        "amount",
        "acct-id",
    ]


def test_adapter_failure_does_not_commit_attempted_tree_and_records_trace() -> None:
    original = _tree()

    class BrokenAdapter(_RecordingAdapter):
        def modify_node(self, query, path, tree, site_id=None, project_id=None):
            tree["poison"] = True
            raise RuntimeError("secret backend detail")

    runtime = OperationToolRuntime(original, action_adapter=BrokenAdapter())
    candidate = next(
        candidate
        for candidate in _search(runtime, "modify_node")["candidates"]
        if candidate["node_id"] == "acct-id"
    )

    with pytest.raises(RuntimeError, match="secret backend detail"):
        runtime.execute("modify_node", _target_args(candidate))

    assert runtime.tree == original
    assert runtime.tree is not original
    assert runtime.version == 0
    assert runtime.operations == []
    assert runtime.traces[-1].success is False
    assert runtime.traces[-1].tool_name == "modify_node"
    assert runtime.traces[-1].tree_version_before == 0
    assert runtime.traces[-1].tree_version_after == 0


def test_invalid_adapter_output_is_atomic() -> None:
    class InvalidAdapter(_RecordingAdapter):
        def modify_node(self, query, path, tree, site_id=None, project_id=None):
            tree["children"].clear()
            return {"target_tree": tree}

    runtime = OperationToolRuntime(_tree(), action_adapter=InvalidAdapter())
    before = deepcopy(runtime.tree)
    candidate = next(
        candidate
        for candidate in _search(runtime, "modify_node")["candidates"]
        if candidate["node_id"] == "acct-id"
    )

    with pytest.raises(ValueError, match="output node ID is absent"):
        runtime.execute("modify_node", _target_args(candidate))

    assert runtime.tree == before
    assert runtime.version == 0
