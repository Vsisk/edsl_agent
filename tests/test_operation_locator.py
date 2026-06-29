from __future__ import annotations

from copy import deepcopy

import pytest

import agent.operation_orchestration.locator as locator_module
from agent.operation_orchestration.locator import OperationLocator
from agent.operation_orchestration.models import LocateOperationRequest, Operation


def _tree() -> dict:
    return {
        "node_id": "root",
        "tree_node_type": "parent",
        "xml_name_property": {"xml_name": "ROOT"},
        "children": [
            {
                "node_id": "leaf",
                "tree_node_type": "simple_leaf",
                "xml_name_property": {"xml_name": "AMOUNT"},
            }
        ],
    }


def _operation(intent_type: str = "modify_node") -> Operation:
    return Operation(op_id="op_0", query="modify amount", intent_type=intent_type)


def test_locate_accepts_an_exact_high_confidence_selection() -> None:
    def gateway(query: str, intent_type: str, candidates: list[dict]) -> dict:
        assert query == "modify amount"
        assert intent_type == "modify_node"
        assert [item["node_id"] for item in candidates] == ["root", "leaf"]
        return {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "The leaf is the requested amount node.",
        }

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation(), target_tree=_tree())
    )

    assert response.success is True
    assert response.operation.status == "located"
    assert response.operation.target_node_id == "leaf"
    assert response.operation.target_jsonpath == "$.children[0]"
    assert [item["node_id"] for item in response.candidates] == ["root", "leaf"]


def test_locate_accepts_medium_confidence() -> None:
    response = OperationLocator(
        lambda _query, _intent, _candidates: {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "medium",
            "reason": "Likely target.",
        }
    ).locate(LocateOperationRequest(operation=_operation(), target_tree=_tree()))

    assert response.success is True
    assert response.operation.target_node_id == "leaf"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "low",
            "reason": "uncertain",
        },
        {
            "selected_node_id": "missing",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "invented id",
        },
        {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.wrong",
            "confidence": "high",
            "reason": "invented path",
        },
        {
            "selected_node_id": "root",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "mixed candidate fields",
        },
        {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "valid except extra",
            "extra": "forbidden",
        },
        {
            "selected_node_id": "   ",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "blank id",
        },
        {
            "selected_node_id": "leaf",
            "selected_jsonpath": "  ",
            "confidence": "high",
            "reason": "blank path",
        },
        {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "  ",
        },
    ],
)
def test_noncreate_rejects_untrusted_or_uncertain_selections(payload: dict) -> None:
    response = OperationLocator(
        lambda _query, _intent, _candidates: payload
    ).locate(LocateOperationRequest(operation=_operation(), target_tree=_tree()))

    assert response.success is False
    assert response.operation.status == "failed"
    assert response.operation.error_message == response.error_message
    assert response.candidates == [
        candidate.model_dump(mode="json")
        for candidate in locator_module.build_node_index(_tree()).values()
    ]


@pytest.mark.parametrize(
    ("selected_node_id", "selected_jsonpath"),
    [
        (" leaf ", "$.children[0]"),
        ("leaf", " $.children[0] "),
    ],
)
def test_noncreate_rejects_padded_selection_fields(
    selected_node_id: str, selected_jsonpath: str
) -> None:
    response = OperationLocator(
        lambda _query, _intent, _candidates: {
            "selected_node_id": selected_node_id,
            "selected_jsonpath": selected_jsonpath,
            "confidence": "high",
            "reason": "leaf",
        }
    ).locate(LocateOperationRequest(operation=_operation(), target_tree=_tree()))

    assert response.success is False
    assert response.operation.status == "failed"
    assert response.operation.target_node_id is None


def test_gateway_exception_fails_a_noncreate_operation() -> None:
    def gateway(_query: str, _intent: str, _candidates: list[dict]) -> dict:
        raise RuntimeError("offline")

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation("delete_node"), target_tree=_tree())
    )

    assert response.success is False
    assert "offline" in (response.error_message or "")


def test_dependent_operation_is_rejected_without_calling_gateway_or_fallback() -> None:
    called = False

    def gateway(_query: str, _intent: str, _candidates: list[dict]) -> dict:
        nonlocal called
        called = True
        raise AssertionError("must not be called")

    operation = _operation("create_node").model_copy(update={"depends_on": ["op_0"]})
    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=operation, target_tree=_tree())
    )

    assert response.success is False
    assert response.operation.status == "failed"
    assert response.operation.target_node_id is None
    assert called is False


@pytest.mark.parametrize(
    "payload_or_error",
    [
        RuntimeError("offline"),
        {
            "selected_node_id": "root",
            "selected_jsonpath": "$",
            "confidence": "low",
            "reason": "uncertain",
        },
        {
            "selected_node_id": "invented",
            "selected_jsonpath": "$",
            "confidence": "high",
            "reason": "invalid",
        },
    ],
)
def test_create_falls_back_to_first_valid_root_candidate(payload_or_error: object) -> None:
    def gateway(_query: str, _intent: str, _candidates: list[dict]) -> dict:
        if isinstance(payload_or_error, Exception):
            raise payload_or_error
        assert isinstance(payload_or_error, dict)
        return payload_or_error

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation("create_node"), target_tree=_tree())
    )

    assert response.success is True
    assert response.operation.status == "located"
    assert response.operation.target_node_id == "root"
    assert response.operation.target_jsonpath == "$"
    assert [candidate["node_id"] for candidate in response.candidates] == ["root"]


@pytest.mark.parametrize(
    ("selected_node_id", "selected_jsonpath"),
    [
        (" nested ", "$.children[0]"),
        ("nested", " $.children[0] "),
    ],
)
def test_create_padded_selection_fields_trigger_root_fallback(
    selected_node_id: str, selected_jsonpath: str
) -> None:
    target_tree = {
        "node_id": "root",
        "tree_node_type": "parent",
        "children": [
            {"node_id": "nested", "tree_node_type": "parent"}
        ],
    }
    response = OperationLocator(
        lambda _query, _intent, _candidates: {
            "selected_node_id": selected_node_id,
            "selected_jsonpath": selected_jsonpath,
            "confidence": "high",
            "reason": "nested",
        }
    ).locate(
        LocateOperationRequest(
            operation=_operation("create_node"), target_tree=target_tree
        )
    )

    assert response.success is True
    assert response.operation.status == "located"
    assert response.operation.target_node_id == "root"
    assert response.operation.target_jsonpath == "$"


def test_create_fails_when_no_valid_root_candidate_exists() -> None:
    target_tree = {
        "node_id": "leaf-root",
        "tree_node_type": "simple_leaf",
        "children": [{"node_id": "nested", "tree_node_type": "parent"}],
    }
    response = OperationLocator(
        lambda _query, _intent, _candidates: (_ for _ in ()).throw(RuntimeError("bad"))
    ).locate(
        LocateOperationRequest(
            operation=_operation("create_node"), target_tree=target_tree
        )
    )

    assert response.success is False
    assert [candidate["node_id"] for candidate in response.candidates] == ["nested"]
    assert "root" in (response.error_message or "").lower()


def test_candidates_are_filtered_by_intent_in_dfs_order() -> None:
    seen: list[list[str]] = []

    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        seen.append([candidate["node_id"] for candidate in candidates])
        return {
            "selected_node_id": "root",
            "selected_jsonpath": "$",
            "confidence": "high",
            "reason": "root",
        }

    OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation("create_node"), target_tree=_tree())
    )
    OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation("modify_node"), target_tree=_tree())
    )

    assert seen == [["root"], ["root", "leaf"]]


def test_default_gateway_passes_prompt_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_generate(prompt_key: str, **kwargs: object) -> dict:
        captured.update(prompt_key=prompt_key, **kwargs)
        return {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "leaf",
        }

    monkeypatch.setattr(locator_module, "generate_by_llm", fake_generate)
    OperationLocator().locate(
        LocateOperationRequest(operation=_operation(), target_tree=_tree())
    )

    assert captured["prompt_key"] == "operation_locator_prompt"
    assert captured["query"] == "modify amount"
    assert captured["intent_type"] == "modify_node"
    assert '"node_id": "leaf"' in str(captured["candidates_json"])


def test_locate_does_not_mutate_request_operation_or_tree() -> None:
    operation = _operation()
    target_tree = _tree()
    operation_before = operation.model_dump(mode="python")
    tree_before = deepcopy(target_tree)

    response = OperationLocator(
        lambda _query, _intent, _candidates: {
            "selected_node_id": "leaf",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "leaf",
        }
    ).locate(LocateOperationRequest(operation=operation, target_tree=target_tree))

    assert response.operation is not operation
    assert operation.model_dump(mode="python") == operation_before
    assert target_tree == tree_before


def test_no_candidates_fails_clearly_without_calling_gateway() -> None:
    called = False

    def gateway(_query: str, _intent: str, _candidates: list[dict]) -> dict:
        nonlocal called
        called = True
        return {}

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation(), target_tree={})
    )

    assert response.success is False
    assert "candidate" in (response.error_message or "").lower()
    assert called is False
