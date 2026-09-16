from __future__ import annotations

from typing import Any, Callable

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import Observation, ObservationSeverity, StageResult
from agent.workflow.value_logic.branches._single_stage import SingleStageBranchWorkflowFactory
from agent.workflow.value_logic.branches.sql.input import BranchWorkflowInput
from agent.workflow.value_logic.result import ValueLogicBranchOutcome
from agent.workflows.expression.definition import ExpressionWorkflowFactory


class ExpressionWorkflowStage(Stage):
    name = "run_expression"
    input_model = BranchWorkflowInput

    def __init__(self, expression_fn: Callable[[Any, Any], Any]) -> None:
        self.expression_fn = expression_fn

    def execute(self, stage_input: BranchWorkflowInput) -> StageResult:
        try:
            result = self.expression_fn(stage_input.request, stage_input.generation_context)
        except Exception as exc:
            outcome = ValueLogicBranchOutcome(
                status="failed",
                branch_type="expression",
                observation=Observation(
                    code="INTERNAL_ERROR",
                    source_stage=self.name,
                    message=str(exc),
                    retryable=False,
                    severity=ObservationSeverity.ERROR,
                ),
            )
            return StageResult(outputs={"branch_outcome": outcome})
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="expression",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


def create_expression_workflow_factory(expression_fn: Callable[[Any, Any], Any]) -> SingleStageBranchWorkflowFactory:
    return SingleStageBranchWorkflowFactory(
        name="expression_generation",
        stage=ExpressionWorkflowStage(expression_fn),
    )

__all__ = [
    "ExpressionWorkflowFactory",
    "ExpressionWorkflowStage",
    "create_expression_workflow_factory",
]
