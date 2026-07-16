from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agent.operation_orchestration.models import OperationToolLoopRequest
from agent.operation_orchestration.tool_loop import OperationToolLoop


def _tree() -> dict[str, Any]:
    return {
        "node_id": "bill",
        "tree_node_type": "parent",
        "xml_name_property": {"xml_name": "BILL_INFO"},
        "children": [],
    }


class _Adapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def create_node(self, query, path, tree):
        tree["children"].append(
            {
                "node_id": "amount",
                "tree_node_type": "simple_leaf",
                "xml_name_property": {"xml_name": "AMOUNT"},
            }
        )
        self.calls.append(("create_node", query, path))
        return {"created_node_id": "amount", "target_tree": tree}

    def generate_expression(
        self, query, path, tree, site_id=None, project_id=None
    ):
        tree["children"][1 if len(tree["children"]) > 1 else 0][
            "data_expression"
        ] = {"expression": query}
        self.calls.append(("generate_expression", query, path))
        return {"target_tree": tree}


def _request(max_steps: int = 10) -> OperationToolLoopRequest:
    return OperationToolLoopRequest(
        query="新增金额字段并生成金额表达式",
        target_tree=_tree(),
        site_id="site",
        project_id="project",
        max_steps=max_steps,
    )


def test_loop_executes_multi_step_task_against_latest_tree() -> None:
    adapter = _Adapter()
    decisions = iter(
        [
            {
                "tool_name": "search_nodes",
                "arguments": {
                    "query": "bill parent",
                    "intent_type": "create_node",
                    "limit": 10,
                },
            },
            {
                "tool_name": "create_node",
                "arguments": {
                    "target_node_id": "bill",
                    "target_jsonpath": "$",
                    "candidate_version": 0,
                    "query": "新增金额字段",
                },
            },
            {
                "tool_name": "search_nodes",
                "arguments": {
                    "query": "amount",
                    "intent_type": "generate_expression",
                    "limit": 10,
                },
            },
            {
                "tool_name": "generate_expression",
                "arguments": {
                    "target_node_id": "amount",
                    "target_jsonpath": "$.children[0]",
                    "candidate_version": 1,
                    "query": "$ctx$.charge.amount",
                },
            },
            {"tool_name": "finish", "arguments": {"summary": "completed"}},
        ]
    )
    gateway_calls: list[dict[str, Any]] = []

    def gateway(**kwargs):
        gateway_calls.append(deepcopy(kwargs))
        return next(decisions)

    response = OperationToolLoop(
        llm_gateway=gateway, action_adapter=adapter
    ).run(_request())

    assert response.success
    assert response.error_message is None
    assert response.tree_version == 2
    assert [operation.intent_type for operation in response.operations] == [
        "create_node",
        "generate_expression",
    ]
    assert response.target_tree["children"][0]["data_expression"] == {
        "expression": "$ctx$.charge.amount"
    }
    assert [trace.tool_name for trace in response.tool_calls] == [
        "search_nodes",
        "create_node",
        "search_nodes",
        "generate_expression",
        "finish",
    ]
    assert gateway_calls[2]["tree_summary"][1]["node_id"] == "amount"
    assert gateway_calls[1]["tool_history"][0]["tool_name"] == "search_nodes"
    assert adapter.calls == [
        ("create_node", "新增金额字段", "$"),
        (
            "generate_expression",
            "$ctx$.charge.amount",
            "$.children[0]",
        ),
    ]


def test_loop_requires_explicit_finish_before_max_steps() -> None:
    response = OperationToolLoop(
        llm_gateway=lambda **_: {
            "tool_name": "search_nodes",
            "arguments": {
                "query": "bill",
                "intent_type": "create_node",
                "limit": 1,
            },
        },
        action_adapter=_Adapter(),
    ).run(_request(max_steps=2))

    assert not response.success
    assert response.error_message == "operation tool loop exceeded max_steps=2"
    assert len(response.tool_calls) == 2
    assert response.tree_version == 0


def test_loop_rejects_forged_location_without_calling_adapter() -> None:
    adapter = _Adapter()
    original = _tree()
    response = OperationToolLoop(
        llm_gateway=lambda **_: {
            "tool_name": "create_node",
            "arguments": {
                "target_node_id": "bill",
                "target_jsonpath": "$",
                "candidate_version": 0,
                "query": "新增字段",
            },
        },
        action_adapter=adapter,
    ).run(_request())

    assert not response.success
    assert response.error_message == "operation tool create_node failed"
    assert response.target_tree == original
    assert adapter.calls == []
    assert response.tool_calls[-1].success is False


@pytest.mark.parametrize("error_type", [RuntimeError, OSError])
def test_loop_hides_gateway_failure_details(error_type) -> None:
    secret = "secret-api-key"

    def broken_gateway(**kwargs):
        raise error_type(secret)

    response = OperationToolLoop(
        llm_gateway=broken_gateway, action_adapter=_Adapter()
    ).run(_request())

    assert not response.success
    assert response.error_message == "operation tool decision failed"
    assert secret not in response.model_dump_json()


def test_loop_rejects_non_strict_decision_payload() -> None:
    response = OperationToolLoop(
        llm_gateway=lambda **_: {
            "tool_name": "finish",
            "arguments": {},
            "unexpected": True,
        },
        action_adapter=_Adapter(),
    ).run(_request())

    assert not response.success
    assert response.error_message == "operation tool decision failed"


def test_operation_tool_loop_prompt_is_registered() -> None:
    prompts = json.loads(Path("prompt.json").read_text(encoding="utf-8"))
    prompt = prompts["operation_tool_loop_prompt"]["zh"]

    assert "{{tool_catalog_json}}" in prompt
    assert "{{tree_summary_json}}" in prompt
    assert "{{tool_history_json}}" in prompt
    assert "one tool" in prompt.lower()
