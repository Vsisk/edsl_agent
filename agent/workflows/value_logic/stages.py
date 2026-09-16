from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.workflow.core import Observation, ObservationSeverity, Stage, StageResult, WorkflowRunState, WorkflowStatus
from agent.workflow.executor import WorkflowRuntime
from agent.workflows.value_logic.outcome import ValueLogicBranchOutcome


@dataclass
class PrepareInput:
    request: Any


@dataclass
class RouteInput:
    target: Any | None = None


@dataclass
class InvokeBranchInput:
    request: Any
    generation_context: Any
    active_branch: str
    parent_state: WorkflowRunState
    environment: Any


@dataclass
class HandleOutcomeInput:
    branch_outcome: ValueLogicBranchOutcome
    branch_history: list[str]


@dataclass
class FinalizeInput:
    value_logic_result: Any


class PrepareValueLogicStage(Stage):
    name = "prepare"
    input_model = PrepareInput

    def __init__(self, prepare_context_fn: Callable[[Any], tuple[Any, Any | None]]) -> None:
        self.prepare_context_fn = prepare_context_fn

    def execute(self, stage_input: PrepareInput) -> StageResult:
        generation_context, target = self.prepare_context_fn(stage_input.request)
        return StageResult(
            outputs={
                "generation_context": generation_context,
                "target": target,
                "branch_history": [],
            }
        )


class RouteValueLogicStage(Stage):
    name = "route"
    input_model = RouteInput

    def execute(self, stage_input: RouteInput) -> StageResult:
        target = stage_input.target
        branch = "expression"
        if target is not None:
            branch = {
                "sql": "sql",
                "table_field": "bo_field",
                "summary": "summary",
            }.get(getattr(target, "primary_branch", None), "expression")
        return StageResult(outputs={"active_branch": branch})


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


class HandleBranchOutcomeStage(Stage):
    name = "handle_outcome"
    input_model = HandleOutcomeInput

    def execute(self, stage_input: HandleOutcomeInput) -> StageResult:
        outcome = stage_input.branch_outcome
        branch_history = list(stage_input.branch_history)
        if outcome.branch_type not in branch_history:
            branch_history.append(outcome.branch_type)

        outputs: dict[str, Any] = {
            "branch_history": branch_history,
            "branch_outcome": outcome,
        }
        if outcome.handoff_artifacts:
            outputs["handoff_artifacts"] = outcome.handoff_artifacts

        if outcome.status == "success":
            outputs["value_logic_result"] = outcome.result
            return StageResult(outputs=outputs)

        if outcome.status == "fallback" and outcome.fallback_target:
            if outcome.fallback_target in branch_history:
                outputs["value_logic_result"] = ValueLogicBranchOutcome(
                    status="failed",
                    branch_type="value_logic",
                    observation=Observation(
                        code="INTERNAL_ERROR",
                        source_stage=self.name,
                        message=f"fallback loop detected for branch: {outcome.fallback_target}",
                        retryable=False,
                        severity=ObservationSeverity.ERROR,
                    ),
                )
                return StageResult(outputs=outputs)
            outputs["active_branch"] = outcome.fallback_target
            return StageResult(outputs=outputs)

        outputs["value_logic_result"] = outcome
        return StageResult(outputs=outputs)


class FinalizeValueLogicResultStage(Stage):
    name = "finalize"
    input_model = FinalizeInput

    def execute(self, stage_input: FinalizeInput) -> StageResult:
        result = stage_input.value_logic_result
        status = WorkflowStatus.FAILED if getattr(result, "status", None) in {"failed", "need_user_input", "escalate"} else None
        signal = None
        if status == WorkflowStatus.FAILED:
            from agent.workflow.core import StageSignal

            signal = StageSignal(type="terminal_failure", reason=getattr(result, "status", None))
        return StageResult(outputs={"final_result": result}, signal=signal)
