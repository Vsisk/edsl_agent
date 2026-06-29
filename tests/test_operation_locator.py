from __future__ import annotations

from copy import deepcopy
import json

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


def _many_node_tree(count: int) -> dict:
    return {
        "nodes": [
            {
                "node_id": f"node-{index}",
                "tree_node_type": "simple_leaf",
                "annotation": f"node {index}",
            }
            for index in range(count)
        ]
    }


def _selection(candidate: dict, confidence: str = "high") -> dict:
    return {
        "selected_node_id": candidate["node_id"],
        "selected_jsonpath": candidate["jsonpath"],
        "confidence": confidence,
        "reason": "selected candidate",
    }


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


def test_location_attempt_clears_stale_runtime_fields_before_failure() -> None:
    operation = Operation(
        op_id="op_stale",
        query="modify amount",
        intent_type="modify_node",
        depends_on=["upstream"],
        target_node_id="stale-node",
        target_jsonpath="$.stale",
        output_node_id="stale-output",
        status="executed",
        error_message="stale error",
    )

    response = OperationLocator(
        lambda _query, _intent, _candidates: (_ for _ in ()).throw(
            AssertionError("must not call gateway")
        )
    ).locate(LocateOperationRequest(operation=operation, target_tree=_tree()))

    assert response.success is False
    assert response.operation.status == "failed"
    assert response.operation.target_node_id is None
    assert response.operation.target_jsonpath is None
    assert response.operation.output_node_id is None
    assert response.operation.error_message != "stale error"


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


def test_create_accepts_padded_reason_without_triggering_root_fallback() -> None:
    target_tree = {
        "node_id": "root",
        "tree_node_type": "parent",
        "children": [
            {"node_id": "nested", "tree_node_type": "parent"}
        ],
    }
    response = OperationLocator(
        lambda _query, _intent, _candidates: {
            "selected_node_id": "nested",
            "selected_jsonpath": "$.children[0]",
            "confidence": "high",
            "reason": "  nested container is the target  ",
        }
    ).locate(
        LocateOperationRequest(
            operation=_operation("create_node"), target_tree=target_tree
        )
    )

    assert response.success is True
    assert response.operation.status == "located"
    assert response.operation.target_node_id == "nested"
    assert response.operation.target_jsonpath == "$.children[0]"


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


def test_gateway_cannot_mutate_authoritative_candidates_or_invent_location() -> None:
    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        candidates[1]["node_id"] = "invented"
        candidates[1]["jsonpath"] = "$.invented"
        candidates[1]["parent_node_id"] = None
        return {
            "selected_node_id": "invented",
            "selected_jsonpath": "$.invented",
            "confidence": "high",
            "reason": "mutated candidate",
        }

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation(), target_tree=_tree())
    )

    assert response.success is False
    assert response.operation.target_node_id is None
    assert [candidate["node_id"] for candidate in response.candidates] == [
        "root",
        "leaf",
    ]
    assert response.candidates[1]["jsonpath"] == "$.children[0]"
    assert response.candidates[1]["parent_node_id"] == "root"


def test_gateway_mutation_cannot_redirect_create_root_fallback() -> None:
    target_tree = {
        "node_id": "root",
        "tree_node_type": "parent",
        "children": [{"node_id": "nested", "tree_node_type": "parent"}],
    }

    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        candidates[0]["parent_node_id"] = "fake-parent"
        candidates[1]["parent_node_id"] = None
        candidates[1]["node_id"] = "invented"
        candidates[1]["jsonpath"] = "$.invented"
        return {
            "selected_node_id": "invented",
            "selected_jsonpath": "$.invented",
            "confidence": "high",
            "reason": "mutated nested candidate",
        }

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(
            operation=_operation("create_node"), target_tree=target_tree
        )
    )

    assert response.success is True
    assert response.operation.target_node_id == "root"
    assert response.operation.target_jsonpath == "$"
    assert response.error_message == "semantic location failed; used create root fallback"
    assert [candidate["parent_node_id"] for candidate in response.candidates] == [
        None,
        "root",
    ]


def test_all_201_candidates_are_searchable_through_bounded_chunks() -> None:
    chunk_sizes: list[int] = []

    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        chunk_sizes.append(len(candidates))
        assert len(candidates) <= 200
        assert len(json.dumps(candidates, ensure_ascii=False).encode("utf-8")) <= 32_000
        if candidates[-1]["node_id"] == "node-200":
            return _selection(candidates[-1])
        return _selection(candidates[0], "low")

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(
            operation=_operation(), target_tree=_many_node_tree(201)
        )
    )

    assert len(chunk_sizes) >= 2
    assert sum(chunk_sizes) == 201
    assert response.success is True
    assert response.operation.target_node_id == "node-200"
    assert len(response.candidates) == 201


def test_prompt_candidates_bound_descriptions_without_changing_response() -> None:
    annotation = "alpha\n\t\x00beta " + ("界" * 1000)
    target_tree = {
        "node_id": "root",
        "tree_node_type": "simple_leaf",
        "annotation": annotation,
        "xml_name_property": {"xml_name": " ROOT\n\tNAME " + ("x" * 500)},
    }
    seen: dict = {}

    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        seen.update(candidates[0])
        return _selection(candidates[0])

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(operation=_operation(), target_tree=target_tree)
    )

    assert response.success is True
    assert seen["annotation"].startswith("alpha beta ")
    assert "\n" not in seen["annotation"]
    assert "\t" not in seen["annotation"]
    assert "\x00" not in seen["annotation"]
    assert len(seen["annotation"]) == 256
    assert len(seen["xml_name"]) == 256
    assert response.candidates[0]["annotation"] == annotation
    assert response.candidates[0]["xml_name"] == target_tree["xml_name_property"]["xml_name"]


def test_locator_chooses_high_over_earlier_medium_across_chunks() -> None:
    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        if any(candidate["node_id"] == "node-200" for candidate in candidates):
            selected = next(
                candidate for candidate in candidates if candidate["node_id"] == "node-200"
            )
            return _selection(selected, "high")
        return _selection(candidates[0], "medium")

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(
            operation=_operation(), target_tree=_many_node_tree(201)
        )
    )

    assert response.operation.target_node_id == "node-200"


def test_locator_breaks_equal_confidence_ties_by_global_dfs_order() -> None:
    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        selected = next(
            (
                candidate
                for candidate in candidates
                if candidate["node_id"] in {"node-5", "node-200"}
            ),
            candidates[0],
        )
        return _selection(selected, "high")

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(
            operation=_operation(), target_tree=_many_node_tree(201)
        )
    )

    assert response.operation.target_node_id == "node-5"


def test_earlier_chunk_exception_does_not_block_later_valid_selection() -> None:
    calls = 0

    def gateway(_query: str, _intent: str, candidates: list[dict]) -> dict:
        nonlocal calls
        calls += 1
        if not any(candidate["node_id"] == "node-200" for candidate in candidates):
            raise RuntimeError("first chunk failed")
        selected = next(
            candidate for candidate in candidates if candidate["node_id"] == "node-200"
        )
        return _selection(selected)

    response = OperationLocator(gateway).locate(
        LocateOperationRequest(
            operation=_operation(), target_tree=_many_node_tree(201)
        )
    )

    assert calls >= 2
    assert response.success is True
    assert response.operation.target_node_id == "node-200"


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
