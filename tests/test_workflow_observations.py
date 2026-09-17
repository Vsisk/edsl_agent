from __future__ import annotations

from dataclasses import dataclass

from agent.workflow import (
    HarnessContext,
    Observation,
    WorkflowDefinition,
    WorkflowRuntime,
)
from agent.workflow.runtime.run_state import WorkflowRunState, WorkflowStatus
from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult
from agent.workflows.expression import (
    ExpressionFailureClassifier,
    ExpressionObservationCode,
)


@dataclass
class EmptyInput:
    pass


class BusinessFailureStage(Stage):
    name = "ast_validation"
    input_model = EmptyInput
    artifact_bindings = {}
    environment_bindings = {}
    optional_artifact_bindings = {}

    def execute(self, stage_input: EmptyInput) -> StageResult:
        return StageResult(
            status="failed",
            outputs={"validation": {"is_valid": False}},
            observation=Observation(
                code=ExpressionObservationCode.UNKNOWN_PROPERTY.value,
                source_stage=self.name,
                message="Unknown property amountx",
                evidence={"property": "amountx"},
                missing_information=["property:amountx"],
                related_artifacts=["ast", "typed_context"],
                retryable=True,
                severity="error",
            ),
        )


def test_runtime_records_structured_observation_for_business_failure() -> None:
    stage = BusinessFailureStage()
    definition = WorkflowDefinition(
        name="expression_generation",
        entry_stage="ast_validation",
        stages={"ast_validation": stage},
        default_transitions={"ast_validation": None},
    )
    state = WorkflowRunState(
        workflow_name="expression_generation",
        workflow_input={},
    )

    final_state = WorkflowRuntime().run(
        definition=definition,
        state=state,
        environment=HarnessContext(),
    )

    assert final_state.status == WorkflowStatus.FAILED
    assert final_state.terminal_reason == "UNKNOWN_PROPERTY"
    assert final_state.observations["ast_validation"].code == "UNKNOWN_PROPERTY"
    assert final_state.artifacts["validation"] == {"is_valid": False}
    assert final_state.stage_trace[0]["observation_code"] == "UNKNOWN_PROPERTY"


def test_classifier_maps_ast_unknown_property() -> None:
    observation = ExpressionFailureClassifier().classify_ast_failure(
        source_stage="ast_validation",
        validation_result={
            "errors": [
                {
                    "error_type": "PROPERTY_NOT_FOUND",
                    "message": "unknown property amountx",
                    "property": "amountx",
                }
            ]
        },
    )

    assert observation.code == "UNKNOWN_PROPERTY"
    assert observation.missing_information == ["property:amountx"]
    assert observation.retryable is True


def test_classifier_maps_ast_function_argument_error() -> None:
    observation = ExpressionFailureClassifier().classify_ast_failure(
        source_stage="ast_validation",
        validation_result={
            "errors": [
                {
                    "error_type": "ARG_COUNT_MISMATCH",
                    "message": "wrong number of arguments for Text.mask",
                    "function": "Text.mask",
                }
            ]
        },
    )

    assert observation.code == "FUNCTION_ARGUMENT_ERROR"
    assert "function:Text.mask" in observation.missing_information


def test_classifier_maps_ast_return_type_mismatch() -> None:
    observation = ExpressionFailureClassifier().classify_ast_failure(
        source_stage="ast_validation",
        validation_result={
            "errors": [
                {
                    "error_type": "TARGET_RETURN_TYPE_MISMATCH",
                    "message": "return type mismatch",
                    "expected_type": "basic.String",
                    "actual_type": "basic.Integer",
                }
            ]
        },
    )

    assert observation.code == "TYPE_MISMATCH"
    assert "expected_type:basic.String" in observation.missing_information
    assert "actual_type:basic.Integer" in observation.missing_information


def test_classifier_maps_ast_syntax_error() -> None:
    observation = ExpressionFailureClassifier().classify_generation_failure(
        source_stage="expression_generate",
        error={"error_type": "PARSE_FAILED", "message": "unexpected token ')'"},
    )

    assert observation.code == "SYNTAX_ERROR"


def test_classifier_maps_resource_failures() -> None:
    classifier = ExpressionFailureClassifier()

    assert (
        classifier.classify_resource_failure(
            source_stage="resource_search",
            error={"message": "no candidate resource found"},
        ).code
        == "RESOURCE_NOT_FOUND"
    )
    assert (
        classifier.classify_resource_failure(
            source_stage="resource_search",
            error={"message": "resource schema metadata mismatch"},
        ).code
        == "RESOURCE_SCHEMA_MISMATCH"
    )
    assert (
        classifier.classify_resource_failure(
            source_stage="resource_search",
            error={"message": "context chain is broken"},
        ).code
        == "RESOURCE_CHAIN_BROKEN"
    )


def test_classifier_maps_spec_insufficient() -> None:
    observation = ExpressionFailureClassifier().classify_spec_failure(
        source_stage="spec_analysis",
        message="query does not contain enough detail",
        missing_information=["target field", "calculation rule"],
    )

    assert observation.code == "SPEC_INSUFFICIENT"
    assert observation.related_artifacts == ["spec"]
