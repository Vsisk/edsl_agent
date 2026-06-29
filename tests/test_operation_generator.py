from __future__ import annotations

import json
import importlib

import pytest

from agent.operation_orchestration.generator import OperationGenerator
from agent.operation_orchestration.models import GenerateOperationsRequest


TARGET_TREE = {
    "node_id": "root",
    "tree_node_type": "parent",
    "xml_name_property": {"xml_name": "ROOT", "secret": "do not send"},
    "annotation": "root node",
    "children": [
        {
            "node_id": "leaf",
            "tree_node_type": "simple_leaf",
            "xml_name_property": {"xml_name": "LEAF"},
            "edsl_semi_struct": {"large": "payload"},
        }
    ],
}


def request(query: str = "创建节点") -> GenerateOperationsRequest:
    return GenerateOperationsRequest(query=query, target_tree=TARGET_TREE)


def test_single_operation_is_normalized_and_runtime_state_is_cleared() -> None:
    def gateway(query: str, target_tree_summary: list[dict[str, object]]) -> dict:
        assert query == "创建节点"
        assert [item["node_id"] for item in target_tree_summary] == ["root", "leaf"]
        return {
            "operations": [
                {
                    "op_id": "draft-7",
                    "query": "创建金额字段",
                    "intent_type": "create_node",
                    "target_jsonpath": "$.children[99]",
                    "target_node_id": "smuggled-target",
                    "output_node_id": "smuggled-output",
                    "status": "executed",
                    "error_message": "smuggled error",
                }
            ]
        }

    response = OperationGenerator(llm_gateway=gateway).generate(request())

    operation = response.operations[0]
    assert operation.op_id == "op_0"
    assert operation.status == "pending"
    assert operation.target_jsonpath is None
    assert operation.target_node_id is None
    assert operation.output_node_id is None
    assert operation.error_message is None


def test_chain_remaps_dependencies_and_only_enriches_create_parent() -> None:
    payload = {
        "operations": [
            {"op_id": "parent", "query": "创建容器", "intent_type": "create_node"},
            {
                "op_id": "child",
                "query": "创建字段",
                "intent_type": "create_node",
                "depends_on": ["parent"],
            },
            {
                "op_id": "expr",
                "query": "生成取值逻辑",
                "intent_type": "generate_expression",
                "depends_on": ["child"],
            },
        ]
    }

    response = OperationGenerator(llm_gateway=lambda *_: payload).generate(request())

    assert [op.op_id for op in response.operations] == ["op_0", "op_1", "op_2"]
    assert response.operations[1].depends_on == ["op_0"]
    assert response.operations[2].depends_on == ["op_1"]
    assert response.operations[0].query.count("需要包含子节点") == 1
    assert "需要包含子节点" not in response.operations[1].query


def test_create_siblings_share_parent_without_artificial_sibling_dependency() -> None:
    payload = {
        "operations": [
            {"op_id": "a", "query": "创建A", "intent_type": "create_node"},
            {
                "op_id": "b",
                "query": "创建B",
                "intent_type": "create_node",
                "depends_on": ["a"],
            },
            {
                "op_id": "c",
                "query": "创建C",
                "intent_type": "create_node",
                "depends_on": ["a"],
            },
        ]
    }

    operations = OperationGenerator(llm_gateway=lambda *_: payload).generate(request()).operations

    assert operations[0].query.count("需要包含子节点") == 1
    assert operations[1].depends_on == ["op_0"]
    assert operations[2].depends_on == ["op_0"]
    assert "op_1" not in operations[2].depends_on


def test_multi_dependency_target_from_is_remapped_and_selects_enrichment_source() -> None:
    payload = {
        "operations": [
            {"op_id": "left", "query": "创建左容器", "intent_type": "create_node"},
            {"op_id": "right", "query": "准备数据", "intent_type": "modify_node"},
            {
                "op_id": "child",
                "query": "创建子节点",
                "intent_type": "create_node",
                "depends_on": ["left", "right"],
                "target_from": "left",
            },
        ]
    }

    operations = OperationGenerator(llm_gateway=lambda *_: payload).generate(request()).operations

    assert operations[2].depends_on == ["op_0", "op_1"]
    assert operations[2].target_from == "op_0"
    assert "需要包含子节点" in operations[0].query
    assert "需要包含子节点" not in operations[1].query


def test_ordering_dependencies_for_non_create_downstream_do_not_enrich() -> None:
    payload = {
        "operations": [
            {"op_id": "a", "query": "创建A", "intent_type": "create_node"},
            {
                "op_id": "b",
                "query": "修改已有节点",
                "intent_type": "modify_node",
                "depends_on": ["a"],
            },
        ]
    }

    operations = OperationGenerator(llm_gateway=lambda *_: payload).generate(request()).operations

    assert "需要包含子节点" not in operations[0].query


def test_duplicate_original_ids_are_rejected_before_remapping() -> None:
    payload = {
        "operations": [
            {"op_id": "same", "query": "A", "intent_type": "create_node"},
            {"op_id": "same", "query": "B", "intent_type": "create_node"},
        ]
    }

    with pytest.raises(ValueError, match="duplicate original operation id.*same"):
        OperationGenerator(llm_gateway=lambda *_: payload).generate(request())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "operations": [
                    {
                        "op_id": "child",
                        "query": "child",
                        "intent_type": "create_node",
                        "depends_on": ["missing"],
                    }
                ]
            },
            "missing dependency",
        ),
        (
            {
                "operations": [
                    {
                        "op_id": "a",
                        "query": "A",
                        "intent_type": "create_node",
                        "depends_on": ["b"],
                    },
                    {
                        "op_id": "b",
                        "query": "B",
                        "intent_type": "create_node",
                        "depends_on": ["a"],
                    },
                ]
            },
            "cycle",
        ),
    ],
)
def test_invalid_dependency_graph_surfaces_as_value_error(payload: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        OperationGenerator(llm_gateway=lambda *_: payload).generate(request())


def test_empty_operations_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one operation"):
        OperationGenerator(llm_gateway=lambda *_: {"operations": []}).generate(request())


def test_gateway_and_payload_errors_surface_with_context() -> None:
    def broken_gateway(*_: object) -> dict:
        raise RuntimeError("offline")

    with pytest.raises(ValueError, match="operation generation gateway failed.*offline"):
        OperationGenerator(llm_gateway=broken_gateway).generate(request())

    with pytest.raises(ValueError, match="invalid operation generation payload"):
        OperationGenerator(llm_gateway=lambda *_: {"operations": "wrong"}).generate(request())


def test_default_gateway_uses_prompt_key_query_and_json_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_generate_by_llm(prompt_key: str, **kwargs: object) -> dict:
        captured["prompt_key"] = prompt_key
        captured.update(kwargs)
        return {
            "operations": [
                {"op_id": "x", "query": "创建节点", "intent_type": "create_node"}
            ]
        }

    gateway_module = importlib.import_module("agent.llm.generate_by_llm")
    monkeypatch.setattr(gateway_module, "generate_by_llm", fake_generate_by_llm)

    OperationGenerator().generate(request("原始需求"))

    assert captured["prompt_key"] == "operation_generator_prompt"
    assert captured["query"] == "原始需求"
    summary = json.loads(str(captured["target_tree_summary_json"]))
    assert [item["node_id"] for item in summary] == ["root", "leaf"]


def test_summary_contains_only_candidate_dumps_not_the_whole_tree() -> None:
    captured: list[dict[str, object]] = []

    def gateway(_: str, target_tree_summary: list[dict[str, object]]) -> dict:
        captured.extend(target_tree_summary)
        return {
            "operations": [
                {"op_id": "x", "query": "创建节点", "intent_type": "create_node"}
            ]
        }

    OperationGenerator(llm_gateway=gateway).generate(request())

    assert [item["node_id"] for item in captured] == ["root", "leaf"]
    assert set(captured[0]) == {
        "node_id",
        "jsonpath",
        "tree_node_type",
        "xml_name",
        "annotation",
        "parent_xml_name",
        "parent_node_id",
        "child_count",
    }
    serialized = json.dumps(captured, ensure_ascii=False)
    assert "do not send" not in serialized
    assert "large" not in serialized
