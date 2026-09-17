from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.workflow import (
    ContextPolicy,
    HarnessContext,
    Observation,
    RetryPolicy,
    TransitionPolicy,
    TransitionRule,
    WorkflowDefinition,
    WorkflowRuntime,
)
from agent.workflow.runtime.run_state import WorkflowRunState, WorkflowStatus
from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult


@dataclass
class SpecInput:
    query: str


@dataclass
class ResourceSearchInput:
    spec: str
    downstream_feedback: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerateInput:
    spec: str
    resources: dict[str, Any]
    downstream_feedback: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidateInput:
    ast: dict[str, Any]
    resources: dict[str, Any]
    downstream_feedback: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalizeInput:
    ast: dict[str, Any]
    validation: dict[str, Any]


class SpecStage(Stage):
    name = "spec"
    input_model = SpecInput
    context_policy = ContextPolicy(
        input_model=SpecInput,
        workflow_input_bindings={"query": "query"},
    )

    def execute(self, stage_input: SpecInput) -> StageResult:
        return StageResult(outputs={"spec": f"spec:{stage_input.query}"})


class ResourceSearchStage(Stage):
    name = "resource_search"
    input_model = ResourceSearchInput
    context_policy = ContextPolicy(
        input_model=ResourceSearchInput,
        artifact_bindings={"spec": "spec"},
        downstream_feedback_field="downstream_feedback",
    )

    def __init__(self) -> None:
        self.inputs: list[ResourceSearchInput] = []

    def execute(self, stage_input: ResourceSearchInput) -> StageResult:
        self.inputs.append(stage_input)
        if stage_input.downstream_feedback.get("missing_type") == "basic.Long":
            return StageResult(
                outputs={
                    "resources": {"selected_resource_ids": ["amount_long"], "return_type": "basic.Long"},
                    "resource_candidates": ["amount_string", "amount_long"],
                    "rejected_resource_ids": ["amount_string"],
                }
            )
        return StageResult(
            outputs={
                "resources": {"selected_resource_ids": ["amount_string"], "return_type": "basic.String"},
                "resource_candidates": ["amount_string", "amount_long"],
            }
        )


class GenerateStage(Stage):
    name = "generate"
    input_model = GenerateInput
    context_policy = ContextPolicy(
        input_model=GenerateInput,
        artifact_bindings={
            "spec": "spec",
            "resources": "resources",
        },
        downstream_feedback_field="downstream_feedback",
    )

    def execute(self, stage_input: GenerateInput) -> StageResult:
        return StageResult(
            outputs={
                "ast": {
                    "expression": "amount",
                    "return_type": stage_input.resources["return_type"],
                },
                "expression": "amount",
            }
        )


class ValidateStage(Stage):
    name = "validate"
    input_model = ValidateInput
    context_policy = ContextPolicy(
        input_model=ValidateInput,
        artifact_bindings={
            "ast": "ast",
            "resources": "resources",
        },
        downstream_feedback_field="downstream_feedback",
    )

    def execute(self, stage_input: ValidateInput) -> StageResult:
        actual = stage_input.ast["return_type"]
        if actual != "basic.Long":
            return StageResult(
                status="failed",
                outputs={
                    "validation": {
                        "is_valid": False,
                        "errors": [{"error_type": "TARGET_RETURN_TYPE_MISMATCH"}],
                    }
                },
                observation=Observation(
                    code="TYPE_MISMATCH",
                    source_stage=self.name,
                    message="return type mismatch",
                    evidence={
                        "expected_type": "basic.Long",
                        "actual_type": actual,
                    },
                    missing_information=["type:basic.Long"],
                    related_artifacts=["ast", "resources"],
                    retryable=True,
                    severity="error",
                ),
            )
        return StageResult(outputs={"validation": {"is_valid": True, "errors": []}})


class FinalizeStage(Stage):
    name = "finalize"
    input_model = FinalizeInput
    context_policy = ContextPolicy(
        input_model=FinalizeInput,
        artifact_bindings={
            "ast": "ast",
            "validation": "validation",
        },
    )

    def execute(self, stage_input: FinalizeInput) -> StageResult:
        return StageResult(outputs={"final_expression": stage_input.ast["expression"]})


def test_expression_workflow_recovers_from_wrong_resource_selection() -> None:
    resource_stage = ResourceSearchStage()
    definition = WorkflowDefinition(
        name="expression_generation",
        entry_stage="spec",
        stages={
            "spec": SpecStage(),
            "resource_search": resource_stage,
            "generate": GenerateStage(),
            "validate": ValidateStage(),
            "finalize": FinalizeStage(),
        },
        default_transitions={
            "spec": "resource_search",
            "resource_search": "generate",
            "generate": "validate",
            "validate": "finalize",
            "finalize": None,
        },
        terminal_stages={"finalize"},
        transition_policy=TransitionPolicy(
            rules=(
                TransitionRule(
                    from_stage="validate",
                    to_stage="resource_search",
                    observation_codes=("TYPE_MISMATCH",),
                ),
            )
        ),
        retry_policy=RetryPolicy(max_total_transitions=12, max_retry_per_stage=3),
    )

    final_state = WorkflowRuntime().run(
        definition=definition,
        state=WorkflowRunState(
            workflow_name="expression_generation",
            workflow_input={"query": "amount should be a long"},
        ),
        environment=HarnessContext(),
    )

    assert final_state.status == WorkflowStatus.COMPLETED
    assert final_state.artifacts["final_expression"] == "amount"
    assert [item["stage"] for item in final_state.stage_trace] == [
        "spec",
        "resource_search",
        "generate",
        "validate",
        "resource_search",
        "generate",
        "validate",
        "finalize",
    ]
    assert [
        (item["from_stage"], item["to_stage"], item["observation_code"])
        for item in final_state.transition_trace
    ] == [
        ("spec", "resource_search", None),
        ("resource_search", "generate", None),
        ("generate", "validate", None),
        ("validate", "resource_search", "TYPE_MISMATCH"),
        ("resource_search", "generate", None),
        ("generate", "validate", None),
        ("validate", "finalize", None),
    ]
    assert len(resource_stage.inputs) == 2
    assert resource_stage.inputs[0].downstream_feedback["validation_error"] is None
    assert resource_stage.inputs[1].downstream_feedback["validation_error"]["code"] == "TYPE_MISMATCH"
    assert resource_stage.inputs[1].downstream_feedback["missing_type"] == "basic.Long"


def test_loop_guard_blocks_same_failure_fingerprint() -> None:
    definition = WorkflowDefinition(
        name="loop_guard",
        entry_stage="validate",
        stages={"validate": ValidateStage()},
        default_transitions={"validate": None},
        transition_policy=TransitionPolicy(
            rules=(
                TransitionRule(
                    from_stage="validate",
                    to_stage="validate",
                    observation_codes=("TYPE_MISMATCH",),
                ),
            )
        ),
        retry_policy=RetryPolicy(
            max_total_transitions=12,
            max_retry_per_stage=5,
            max_same_failure_fingerprint=1,
        ),
    )
    state = WorkflowRunState(
        workflow_name="loop_guard",
        workflow_input={},
        artifacts={
            "ast": {"expression": "amount", "return_type": "basic.String"},
            "resources": {"selected_resource_ids": ["amount_string"], "return_type": "basic.String"},
        },
    )

    final_state = WorkflowRuntime().run(
        definition=definition,
        state=state,
        environment=HarnessContext(),
    )

    assert final_state.status == WorkflowStatus.FAILED
    assert final_state.terminal_reason == "same_failure_fingerprint"
    assert final_state.transition_trace[-1]["allowed"] is False
