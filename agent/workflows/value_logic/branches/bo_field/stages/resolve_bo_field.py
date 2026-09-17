from __future__ import annotations

from typing import Any, Callable

from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import StageResult
from agent.workflows.value_logic.branches.bo_field.input import BoFieldWorkflowInput
from agent.workflows.value_logic.result import ValueLogicBranchOutcome


class BoFieldWorkflowStage(Stage):
    name = "resolve_bo_field"
    input_model = BoFieldWorkflowInput

    def __init__(self, resolve_bo_field_fn: Callable[[Any, Any], Any | None]) -> None:
        self.resolve_bo_field_fn = resolve_bo_field_fn

    def execute(self, stage_input: BoFieldWorkflowInput) -> StageResult:
        result = self.resolve_bo_field_fn(stage_input.request, stage_input.generation_context)
        if isinstance(result, ValueLogicBranchOutcome):
            outcome = result
        elif result is None:
            outcome = ValueLogicBranchOutcome(
                status="fallback",
                branch_type="bo_field",
                fallback_target="expression",
                handoff_artifacts={},
            )
        else:
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="bo_field",
                result=result,
            )
        return StageResult(outputs={"branch_outcome": outcome})


__all__ = ["BoFieldWorkflowStage"]
