from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.workflow.runtime.run_state import WorkflowRunState
from agent.workflow.runtime.runtime import WorkflowRuntime
from agent.workflow.runtime.stage import Stage
from agent.workflow.runtime.stage_result import Observation, ObservationSeverity, StageResult
from agent.workflow.value_logic.result import ValueLogicBranchOutcome


@dataclass
class InvokeBranchInput:
    request: Any
    generation_context: Any
    active_branch: str
    parent_state: WorkflowRunState
    environment: Any


class InvokeBranchStage(Stage):
    name = "invoke_branch"
    input_model = InvokeBranchInput

    def __init__(
        self,
        *,
        runtime: WorkflowRuntime,
        sql_workflow_factory: Any,
        bo_field_workflow_factory: Any,
        expression_workflow_factory: Any,
        summary_fn: Callable[[Any, Any], Any],
    ) -> None:
        self.runtime = runtime
        self.sql_workflow_factory = sql_workflow_factory
        self.bo_field_workflow_factory = bo_field_workflow_factory
        self.expression_workflow_factory = expression_workflow_factory
        self.summary_fn = summary_fn

    def execute(self, stage_input: InvokeBranchInput) -> StageResult:
        branch = stage_input.active_branch
        if branch == "summary":
            outcome = ValueLogicBranchOutcome(
                status="success",
                branch_type="summary",
                result=self.summary_fn(stage_input.request, stage_input.generation_context),
            )
            return StageResult(outputs={"branch_outcome": outcome})
        factory = {
            "sql": self.sql_workflow_factory,
            "bo_field": self.bo_field_workflow_factory,
            "expression": self.expression_workflow_factory,
        }.get(branch)
        if factory is None:
            outcome = ValueLogicBranchOutcome(
                status="failed",
                branch_type="value_logic",
                observation=Observation(
                    code="INTERNAL_ERROR",
                    source_stage=self.name,
                    message=f"unsupported value logic branch: {branch}",
                    retryable=False,
                    severity=ObservationSeverity.ERROR,
                ),
            )
            return StageResult(outputs={"branch_outcome": outcome})

        child = self.runtime.run_child(
            definition=factory.create_definition(),
            parent_state=stage_input.parent_state,
            workflow_input={"request": stage_input.request},
            environment=stage_input.environment,
            inherited_artifacts={"generation_context": stage_input.generation_context},
        )
        outcome = child.state.require_artifact("branch_outcome")
        outcome.child_run_id = child.state.run_id
        return StageResult(
            outputs={
                "branch_outcome": outcome,
                "child_run_id": child.state.run_id,
            }
        )


__all__ = ["InvokeBranchInput", "InvokeBranchStage"]
